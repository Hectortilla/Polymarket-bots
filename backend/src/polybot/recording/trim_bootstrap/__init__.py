from __future__ import annotations

from polybot.backtesting.state import ArchiveMarketState
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.archive.writer import RecordingArchive
from polybot.recording.contracts.book import BookBaselinePayload, BookDeltaPayload
from polybot.recording.contracts.market import MarketIdentity, MarketMetadataPayload
from polybot.recording.contracts.records import BookCheckpoint, RecordedEvent
from polybot.recording.trim_bootstrap.books import (
    BootstrapBook,
    BootstrapState,
    bootstrap_books,
)
from polybot.recording.trim_bootstrap.recovery import RecoveryBootstrap
from polybot.recording.trim_contracts import RecordingTrimPlan
from polybot.recording.trim_recovery import TrimRecovery
from polybot.recording.trim_recovery.boundaries import recovery_sequence_cutoffs


class TrimBootstrap:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def write(
        self,
        plan: RecordingTrimPlan,
        archive: RecordingArchive,
    ) -> int:
        prime_at_ms = plan.start_at_ms - 1
        if prime_at_ms < 0:
            return 0
        markets = tuple(
            market
            for market in self._reader.markets_at(
                prime_at_ms,
                session_id=plan.source_session.session_id,
                market_slugs=plan.market_slugs,
                allow_gaps=True,
            )
            if not market.resolved
        )
        events: list[RecordedEvent] = []
        books_by_condition: dict[str, tuple[BootstrapBook, ...]] = {}
        next_sequence = archive.next_sequence
        for market in markets:
            bootstrap_state = self.state_before(plan, market, prime_at_ms)
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
                    payload=bootstrap_state.metadata,
                )
            )
            next_sequence += 1
            bootstrap_books = bootstrap_state.books
            books_by_condition[market.condition_id] = bootstrap_books
            for bootstrap_book in bootstrap_books:
                events.append(
                    RecordedEvent(
                        sequence=next_sequence,
                        session_id=archive.session_id,
                        subscription_generation=bootstrap_book.generation,
                        observed_at_ms=plan.start_at_ms,
                        source_timestamp_ms=None,
                        identity=bootstrap_book.identity,
                        payload=bootstrap_book.book,
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

    def state_before(
        self,
        plan: RecordingTrimPlan,
        market: MarketMetadataPayload,
        prime_at_ms: int,
    ) -> BootstrapState:
        recovery_boundaries = TrimRecovery(self._reader).token_boundaries(
            session=plan.source_session,
            market=market,
            boundary_at_ms=plan.start_at_ms,
        )
        has_boundary_baselines = self._reader.has_complete_baseline_pair(
            market,
            start_at_ms=plan.start_at_ms,
            end_at_ms=plan.start_at_ms,
            session_id=plan.source_session.session_id,
            after_sequence_by_token=recovery_sequence_cutoffs(recovery_boundaries),
        )
        if recovery_boundaries is not None and not has_boundary_baselines:
            checkpoints = self._reader.checkpoint_pair_at(
                market.condition_id,
                plan.start_at_ms,
                session_id=plan.source_session.session_id,
            )
            if checkpoints is not None:
                return RecoveryBootstrap(self._reader).state_at_checkpoint(
                    plan,
                    market,
                    checkpoints,
                    scan_boundaries=recovery_boundaries,
                )

        materialized_metadata = self._reader.market_state_at(
            market.condition_id,
            prime_at_ms,
            allow_gaps=True,
        )
        if materialized_metadata is None:
            materialized_metadata = market
        scan_start_ms = TrimRecovery(self._reader).clean_scan_start(
            session=plan.source_session,
            condition_id=market.condition_id,
            through_ms=prime_at_ms,
        )
        if scan_start_ms is None:
            return BootstrapState(materialized_metadata, ())

        state = ArchiveMarketState()
        state.add_metadata(materialized_metadata)
        generation_by_token: dict[str, int] = {}
        for event in self._reader.iter_events(
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

        books = bootstrap_books(state, market, generation_by_token)
        return BootstrapState(materialized_metadata, books)
