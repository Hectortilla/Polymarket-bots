"""Self-contained state materialization at a trimmed interval boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace

from polybot.backtesting.state import ArchiveMarketState

from .archive import RecordingArchive, RecordingReader
from .contracts import (
    BookBaselinePayload,
    BookCheckpoint,
    BookDeltaPayload,
    CoverageGapPayload,
    MarketIdentity,
    MarketMetadataPayload,
    RecordedBookLevel,
    RecordedEvent,
    ResolutionPayload,
    TickSizeChangePayload,
)
from .trim_contracts import RecordingTrimError, RecordingTrimPlan
from .trim_recovery import (
    RecoveryTokenBoundary,
    recovery_sequence_cutoffs,
    recovery_token_boundaries,
)


@dataclass(frozen=True, slots=True)
class _BootstrapBook:
    identity: MarketIdentity
    generation: int
    book: BookBaselinePayload


@dataclass(frozen=True, slots=True)
class _BootstrapState:
    metadata: MarketMetadataPayload
    books: tuple[_BootstrapBook, ...]


def write_trim_bootstrap(
    source: RecordingReader,
    plan: RecordingTrimPlan,
    archive: RecordingArchive,
) -> int:
    prime_at_ms = plan.start_at_ms - 1
    if prime_at_ms < 0:
        return 0
    markets = source.markets_at(
        prime_at_ms,
        session_id=plan.source_session.session_id,
        market_slugs=plan.market_slugs,
        allow_gaps=True,
    )
    events: list[RecordedEvent] = []
    books_by_condition: dict[str, tuple[_BootstrapBook, ...]] = {}
    next_sequence = archive.next_sequence
    for market in markets:
        bootstrap = _state_before(source, plan, market, prime_at_ms)
        events.append(
            RecordedEvent(
                sequence=next_sequence,
                session_id=archive.session_id,
                subscription_generation=0,
                observed_at_ms=plan.start_at_ms,
                source_timestamp_ms=None,
                identity=MarketIdentity(
                    condition_id=market.condition_id,
                    market_slug=market.market_slug,
                ),
                payload=bootstrap.metadata,
            )
        )
        next_sequence += 1
        bootstrap_books = bootstrap.books
        books_by_condition[market.condition_id] = bootstrap_books
        for bootstrap in bootstrap_books:
            events.append(
                RecordedEvent(
                    sequence=next_sequence,
                    session_id=archive.session_id,
                    subscription_generation=bootstrap.generation,
                    observed_at_ms=plan.start_at_ms,
                    source_timestamp_ms=None,
                    identity=bootstrap.identity,
                    payload=bootstrap.book,
                )
            )
            next_sequence += 1
    archive.append_events(events)

    checkpoint_sequence = archive.next_sequence - 1
    checkpoints: list[BookCheckpoint] = []
    for market in markets:
        books = books_by_condition[market.condition_id]
        generations = {book.generation for book in books}
        if len(books) != len(market.outcomes) or len(generations) != 1:
            continue
        generation = generations.pop()
        checkpoints.extend(
            BookCheckpoint(
                sequence=checkpoint_sequence,
                session_id=archive.session_id,
                subscription_generation=generation,
                observed_at_ms=plan.start_at_ms,
                identity=book.identity,
                book=book.book,
            )
            for book in books
        )
    archive.append_checkpoints(checkpoints)
    return len(events)


def _state_before(
    source: RecordingReader,
    plan: RecordingTrimPlan,
    market: MarketMetadataPayload,
    prime_at_ms: int,
) -> _BootstrapState:
    recovery_boundaries = recovery_token_boundaries(
        source,
        session=plan.source_session,
        market=market,
        boundary_at_ms=plan.start_at_ms,
    )
    has_boundary_baselines = source.has_complete_baseline_pair(
        market,
        start_at_ms=plan.start_at_ms,
        end_at_ms=plan.start_at_ms,
        session_id=plan.source_session.session_id,
        after_sequence_by_token=recovery_sequence_cutoffs(
            recovery_boundaries
        ),
    )
    if recovery_boundaries is not None and not has_boundary_baselines:
        checkpoints = source.checkpoint_pair_at(
            market.condition_id,
            plan.start_at_ms,
            session_id=plan.source_session.session_id,
        )
        if checkpoints is not None:
            return _state_at_recovery_checkpoint(
                source,
                plan,
                market,
                checkpoints,
                scan_boundaries=recovery_boundaries,
            )

    materialized_metadata = source.market_state_at(
        market.condition_id,
        prime_at_ms,
        allow_gaps=True,
    )
    if materialized_metadata is None:
        materialized_metadata = market
    scan_start_ms = plan.source_session.started_at_ms
    for record in source.coverage_gaps(
        start_at_ms=scan_start_ms,
        end_at_ms=prime_at_ms,
        session_id=plan.source_session.session_id,
        condition_id=market.condition_id,
    ):
        if record.gap.ended_at_ms is None:
            return _BootstrapState(materialized_metadata, ())
        scan_start_ms = max(scan_start_ms, record.gap.ended_at_ms)
    if scan_start_ms > prime_at_ms:
        return _BootstrapState(materialized_metadata, ())

    state = ArchiveMarketState()
    state.add_metadata(materialized_metadata)
    generation_by_token: dict[str, int] = {}
    for event in source.iter_events(
        start_at_ms=scan_start_ms,
        end_at_ms=prime_at_ms,
        session_id=plan.source_session.session_id,
        condition_id=market.condition_id,
    ):
        if not isinstance(
            event.payload,
            (BookBaselinePayload, BookDeltaPayload),
        ):
            continue
        state.apply(event)
        if isinstance(event.payload, BookBaselinePayload):
            generation_by_token[event.payload.token_id] = (
                event.subscription_generation
            )

    books = _bootstrap_books(state, market, generation_by_token)
    return _BootstrapState(materialized_metadata, books)


def _state_at_recovery_checkpoint(
    source: RecordingReader,
    plan: RecordingTrimPlan,
    market: MarketMetadataPayload,
    checkpoints: tuple[BookCheckpoint, BookCheckpoint],
    *,
    scan_boundaries: tuple[RecoveryTokenBoundary, ...],
) -> _BootstrapState:
    boundary_sequence = checkpoints[0].sequence
    materialized_metadata = source.market_state_at(
        market.condition_id,
        plan.start_at_ms,
        sequence_cutoff=boundary_sequence,
        allow_gaps=True,
    )
    if materialized_metadata is None:
        raise RecordingTrimError(
            "recovery checkpoint has no preceding market metadata: "
            f"{market.market_slug}"
        )
    state = ArchiveMarketState()
    state.add_metadata(materialized_metadata)
    generation_by_token: dict[str, int] = {}
    sequence_cutoff_by_token = {
        boundary.token_id: boundary.after_sequence
        for boundary in scan_boundaries
    }
    for event in source.iter_events(
        start_at_ms=min(
            boundary.start_at_ms for boundary in scan_boundaries
        ),
        end_at_ms=plan.start_at_ms,
        session_id=plan.source_session.session_id,
        condition_id=market.condition_id,
        allow_gaps=True,
    ):
        if event.sequence > boundary_sequence:
            if (
                event.observed_at_ms < plan.start_at_ms
                and _is_checkpoint_state_event(event)
            ):
                raise RecordingTrimError(
                    "recovery checkpoint precedes canonical book state at its "
                    f"observation: {market.market_slug}"
                )
            continue
        if isinstance(event.payload, BookBaselinePayload):
            token_id = event.payload.token_id
            if event.sequence <= sequence_cutoff_by_token[token_id]:
                continue
            state.apply(event)
            generation_by_token[token_id] = event.subscription_generation
            continue
        if isinstance(event.payload, BookDeltaPayload):
            changes = tuple(
                change
                for change in event.payload.changes
                if event.sequence > sequence_cutoff_by_token[change.token_id]
            )
            if not changes:
                continue
            state.apply(
                event
                if changes == event.payload.changes
                else replace(
                    event,
                    payload=BookDeltaPayload(changes=changes),
                )
            )

    books = _bootstrap_books(state, market, generation_by_token)
    checkpoint_by_token = {
        checkpoint.book.token_id: checkpoint for checkpoint in checkpoints
    }
    if len(books) != len(market.outcomes) or any(
        checkpoint_by_token.get(book.book.token_id) is None
        or checkpoint_by_token[book.book.token_id].subscription_generation
        != book.generation
        or checkpoint_by_token[book.book.token_id].book != book.book
        for book in books
    ):
        raise RecordingTrimError(
            "recovery checkpoint does not match canonical book baselines: "
            f"{market.market_slug}"
        )
    return _BootstrapState(materialized_metadata, books)


def _is_checkpoint_state_event(event: RecordedEvent) -> bool:
    return isinstance(
        event.payload,
        (
            MarketMetadataPayload,
            BookBaselinePayload,
            BookDeltaPayload,
            TickSizeChangePayload,
            ResolutionPayload,
            CoverageGapPayload,
        ),
    )


def _bootstrap_books(
    state: ArchiveMarketState,
    market: MarketMetadataPayload,
    generation_by_token: dict[str, int],
) -> tuple[_BootstrapBook, ...]:
    books = state.books
    result: list[_BootstrapBook] = []
    for outcome in market.outcomes:
        snapshot = books.get(outcome.token_id)
        generation = generation_by_token.get(outcome.token_id)
        if snapshot is None or generation is None:
            continue
        result.append(
            _BootstrapBook(
                identity=MarketIdentity(
                    condition_id=market.condition_id,
                    market_slug=market.market_slug,
                    token_id=outcome.token_id,
                ),
                generation=generation,
                book=BookBaselinePayload(
                    token_id=outcome.token_id,
                    bids=tuple(
                        RecordedBookLevel(level.price, level.size)
                        for level in snapshot.bids
                    ),
                    asks=tuple(
                        RecordedBookLevel(level.price, level.size)
                        for level in snapshot.asks
                    ),
                ),
            )
        )
    return tuple(result)
