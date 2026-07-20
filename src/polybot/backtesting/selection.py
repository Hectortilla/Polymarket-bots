"""Selection and archive-coverage validation for deterministic replay."""

from __future__ import annotations

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestOptions,
    BacktestSelection,
)
from polybot.recording.archive import RecordingReader
from polybot.recording.archive_errors import ArchiveCoverageError
from polybot.recording.archive_models import RecordingSession
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookCheckpoint,
    SessionIntegrityStatus,
)


def resolve_backtest_selection(
    reader: RecordingReader,
    session: RecordingSession,
    options: BacktestOptions,
) -> BacktestSelection:
    """Resolve and gap-check one requested session, range, and market set."""

    effective_end_at_ms = replayable_session_end(reader, session)
    if effective_end_at_ms is None:
        raise BacktestError(
            BacktestFailureReason.SESSION_NOT_REPLAYABLE,
            f"recording session {session.session_id} is not cleanly replayable",
        )
    requested_start = (
        session.started_at_ms
        if options.start_at_ms is None
        else options.start_at_ms
    )
    requested_end = (
        effective_end_at_ms
        if options.end_at_ms is None
        else options.end_at_ms
    )
    if (
        requested_start < session.started_at_ms
        or requested_end > effective_end_at_ms
        or requested_end < requested_start
    ):
        raise BacktestError(
            BacktestFailureReason.INVALID_SELECTION,
            "backtest range must lie inside the selected recording session",
        )
    available_markets = reader.markets_at(
        requested_end,
        session_id=session.session_id,
        allow_gaps=True,
    )
    available_slugs = tuple(
        sorted({market.market_slug for market in available_markets})
    )
    selected_slugs = options.market_slugs or available_slugs
    missing = sorted(set(selected_slugs).difference(available_slugs))
    if missing:
        raise BacktestError(
            BacktestFailureReason.MISSING_MARKET_DATA,
            "selected markets are absent from the recording session: "
            + ", ".join(missing),
        )
    if not selected_slugs:
        raise BacktestError(
            BacktestFailureReason.EMPTY_SELECTION,
            "selected recording session contains no market data",
        )
    bounds = reader.event_bounds(
        start_at_ms=requested_start,
        end_at_ms=requested_end,
        session_id=session.session_id,
        market_slugs=selected_slugs,
    )
    if bounds is None:
        raise BacktestError(
            BacktestFailureReason.EMPTY_SELECTION,
            "selected recording range contains no events",
        )
    start_at_ms = (
        bounds.start_at_ms if options.start_at_ms is None else requested_start
    )
    return BacktestSelection(
        session_id=session.session_id,
        start_at_ms=start_at_ms,
        end_at_ms=requested_end,
        market_slugs=tuple(selected_slugs),
        replay_cutoff_sequence=reader.replay_cutoff_sequence,
        session_integrity_status=session.integrity_status,
        uses_partial_session=(
            session.integrity_status is not SessionIntegrityStatus.COMPLETE
        ),
    )


def replayable_session_end(
    reader: RecordingReader,
    session: RecordingSession,
) -> int | None:
    """Return the replayable session boundary, including a durable partial end."""

    if session.integrity_status is SessionIntegrityStatus.ACTIVE:
        return None
    if (
        session.integrity_status is SessionIntegrityStatus.COMPLETE
        and not session.clean_close
    ):
        return None
    if session.clean_close:
        return session.ended_at_ms
    if session.integrity_status not in {
        SessionIntegrityStatus.INCOMPLETE,
        SessionIntegrityStatus.FAILED,
    }:
        return None
    durable_end_at_ms = reader.session_durable_end_at_ms(session.session_id)
    if durable_end_at_ms is None:
        return None
    if session.ended_at_ms is None:
        return durable_end_at_ms
    return min(session.ended_at_ms, durable_end_at_ms)


def validate_backtest_selection(
    reader: RecordingReader,
    selection: BacktestSelection,
) -> None:
    """Semantically validate selected events and their replay bootstrap."""

    baseline_tokens: dict[tuple[str, int], set[str]] = {}
    for event in reader.iter_events(
        start_at_ms=selection.start_at_ms,
        end_at_ms=selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
    ):
        if not isinstance(event.payload, BookBaselinePayload):
            continue
        condition_id = None if event.identity is None else event.identity.condition_id
        if condition_id is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"book baseline event {event.sequence} has no market identity",
            )
        baseline_tokens.setdefault(
            (condition_id, event.subscription_generation),
            set(),
        ).add(event.payload.token_id)

    markets = reader.markets_at(
        selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
    )
    for market in markets:
        required_tokens = {outcome.token_id for outcome in market.outcomes}
        if any(
            condition_id == market.condition_id
            and required_tokens.issubset(tokens)
            for (condition_id, _), tokens in baseline_tokens.items()
        ):
            continue
        checkpoint_pair = replay_start_checkpoint_pair(
            reader,
            condition_id=market.condition_id,
            start_at_ms=selection.start_at_ms,
            session_id=selection.session_id,
        )
        if checkpoint_pair is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                "selected market has no complete two-token baseline or checkpoint: "
                f"{market.market_slug}",
            )


def validate_backtest_selection_coverage(
    reader: RecordingReader,
    selection: BacktestSelection,
) -> None:
    """Validate indexed bootstrap coverage without scanning all replay events."""

    markets = reader.markets_at(
        selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
    )
    for market in markets:
        if reader.has_complete_baseline_pair(
            market,
            start_at_ms=selection.start_at_ms,
            end_at_ms=selection.end_at_ms,
            session_id=selection.session_id,
        ):
            continue
        checkpoint_pair = replay_start_checkpoint_pair(
            reader,
            condition_id=market.condition_id,
            start_at_ms=selection.start_at_ms,
            session_id=selection.session_id,
        )
        if checkpoint_pair is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                "selected market has no complete two-token baseline or checkpoint: "
                f"{market.market_slug}",
            )


def replay_start_checkpoint_pair(
    reader: RecordingReader,
    *,
    condition_id: str,
    start_at_ms: int,
    session_id: int,
) -> tuple[BookCheckpoint, BookCheckpoint] | None:
    """Find a clean pre-start pair or a common recovery pair at the boundary."""

    prime_at_ms = start_at_ms - 1
    if prime_at_ms >= 0:
        try:
            checkpoints = reader.checkpoint_pair_before(
                condition_id,
                prime_at_ms,
                session_id=session_id,
            )
        except ArchiveCoverageError:
            checkpoints = None
        if checkpoints is not None:
            return checkpoints
    return reader.checkpoint_pair_at(
        condition_id,
        start_at_ms,
        session_id=session_id,
    )
