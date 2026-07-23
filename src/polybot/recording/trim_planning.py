"""Largest replayable-interval selection for recording maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestOptions,
    BacktestSelection,
)
from polybot.backtesting.selection import (
    replayable_session_end,
    replay_start_checkpoint_pair,
    resolve_backtest_selection,
)

from .archive.reader import RecordingReader
from .archive.errors import ArchiveFormatError, RecordingArchiveError
from .archive.models import RecordingSession
from .contracts.records import CoverageGapRecord
from .contracts.market import MarketMetadataPayload
from .trim_contracts import RecordingTrimError, RecordingTrimPlan
from .trim_recovery import (
    clean_scan_start_after_gaps,
    recovery_sequence_cutoffs,
    recovery_token_boundaries,
)


@dataclass(frozen=True, slots=True)
class _CleanInterval:
    start_at_ms: int
    end_at_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_at_ms - self.start_at_ms


def plan_recording_trim(
    reader: RecordingReader,
    *,
    archive_path: Path,
    session_id: int | None,
) -> RecordingTrimPlan:
    """Choose the longest all-market clean interval in one selected session."""

    sessions = reader.sessions()
    if session_id is None and len(sessions) > 1:
        available_ids = ", ".join(str(session.session_id) for session in sessions)
        raise ArchiveFormatError(
            "recording archive requires an explicit --session ID; "
            f"available session IDs: {available_ids}"
        )
    session = reader.select_session(session_id)
    session_end = replayable_session_end(reader, session)
    if session_end is None:
        raise RecordingTrimError(
            f"recording session {session.session_id} has no replayable boundary"
        )
    markets = reader.markets_at(
        session_end,
        session_id=session.session_id,
        allow_gaps=True,
    )
    market_slugs = tuple(sorted({market.market_slug for market in markets}))
    if not market_slugs:
        raise RecordingTrimError(
            f"recording session {session.session_id} contains no market data"
        )
    affecting_gaps = reader.coverage_gaps(
        start_at_ms=session.started_at_ms,
        end_at_ms=session_end,
        session_id=session.session_id,
        market_slugs=market_slugs,
    )
    raw_intervals_list: list[_CleanInterval] = []
    for interval in _clean_intervals(
        session.started_at_ms,
        session_end,
        affecting_gaps,
    ):
        normalized = _normalize_initial_interval(
            reader,
            interval=interval,
            session=session,
            market_slugs=market_slugs,
        )
        if normalized is not None:
            raw_intervals_list.append(normalized)
    raw_intervals = tuple(raw_intervals_list)
    candidates = set(raw_intervals)
    expanded_intervals: set[_CleanInterval] = set()
    failures: list[str] = []
    while candidates:
        candidate = min(candidates, key=_candidate_sort_key)
        candidates.remove(candidate)
        recovery_suffixes = _recovery_boundary_suffixes(
            reader,
            interval=candidate,
            session=session,
            market_slugs=market_slugs,
        )
        if recovery_suffixes:
            candidates.update(recovery_suffixes)
            continue
        try:
            options = BacktestOptions(
                archive_path=archive_path,
                session_id=session.session_id,
                start_at_ms=candidate.start_at_ms,
                end_at_ms=candidate.end_at_ms,
            )
            selection = resolve_backtest_selection(reader, session, options)
            retained_market_slugs = _retained_market_slugs(
                reader,
                selection=selection,
                session=session,
            )
            if not retained_market_slugs:
                raise BacktestError(
                    BacktestFailureReason.EMPTY_SELECTION,
                    "selected recording range contains no active market data",
                )
            selection = resolve_backtest_selection(
                reader,
                session,
                BacktestOptions(
                    archive_path=archive_path,
                    session_id=session.session_id,
                    start_at_ms=candidate.start_at_ms,
                    end_at_ms=candidate.end_at_ms,
                    market_slugs=retained_market_slugs,
                ),
            )
            _validate_trim_selection_coverage(reader, selection, session)
        except (BacktestError, RecordingArchiveError, ValueError) as error:
            failures.append(str(error))
            first_expansion = candidate not in expanded_intervals
            if first_expansion:
                expanded_intervals.add(candidate)
                candidates.update(
                    _suffixes_at_common_checkpoints(
                        reader,
                        interval=candidate,
                        session=session,
                        market_slugs=market_slugs,
                    )
                )
            if candidate in raw_intervals and first_expansion:
                candidates.update(
                    _prefixes_before_late_markets(
                        reader,
                        interval=candidate,
                        session=session,
                        market_slugs=market_slugs,
                    )
                )
            continue
        return RecordingTrimPlan(
            archive_path=archive_path,
            target_identity=reader.target_identity,
            source_session=session,
            start_at_ms=selection.start_at_ms,
            end_at_ms=selection.end_at_ms,
            market_slugs=selection.market_slugs,
            source_event_count=reader.event_count(
                start_at_ms=selection.start_at_ms,
                end_at_ms=selection.end_at_ms,
                session_id=session.session_id,
                market_slugs=selection.market_slugs,
            ),
            source_gap_count=len(
                reader.coverage_gaps(session_id=session.session_id)
            ),
            source_size_bytes=archive_path.stat().st_size,
        )

    detail = "" if not failures else f": {failures[0]}"
    raise RecordingTrimError(
        "recording has no gap-free interval that passes replay validation"
        f"{detail}"
    )


def _candidate_sort_key(value: _CleanInterval) -> tuple[int, int, int]:
    return (-value.duration_ms, value.start_at_ms, value.end_at_ms)


def _retained_market_slugs(
    reader: RecordingReader,
    *,
    selection: BacktestSelection,
    session: RecordingSession,
) -> tuple[str, ...]:
    """Keep market state needed at the boundary or observed inside the interval."""

    markets_at_start = (
        ()
        if selection.start_at_ms == 0
        else reader.markets_at(
            selection.start_at_ms - 1,
            session_id=session.session_id,
            market_slugs=selection.market_slugs,
            allow_gaps=True,
        )
    )
    known_at_start = {market.market_slug for market in markets_at_start}
    active_at_start = {
        market.market_slug
        for market in markets_at_start
        if not market.resolved
    }
    introduced_in_range = set(
        reader.market_slugs_with_metadata_revisions(
            start_at_ms=selection.start_at_ms,
            end_at_ms=selection.end_at_ms,
            session_id=session.session_id,
            market_slugs=selection.market_slugs,
            allow_gaps=True,
        )
    ) - known_at_start
    # A resolved market can still receive a metadata refresh after its resolution.
    # It has no replayable state at the new boundary, so retaining that refresh
    # would make the trimmed archive fail its own baseline validation.
    return tuple(sorted(active_at_start | introduced_in_range))


def _validate_trim_selection_coverage(
    reader: RecordingReader,
    selection: BacktestSelection,
    session: RecordingSession,
) -> None:
    markets = reader.markets_at(
        selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
    )
    for market in markets:
        sequence_cutoffs = _recovery_sequence_cutoffs(
            reader,
            market=market,
            start_at_ms=selection.start_at_ms,
            session=session,
        )
        if reader.has_complete_baseline_pair(
            market,
            start_at_ms=selection.start_at_ms,
            end_at_ms=selection.end_at_ms,
            session_id=selection.session_id,
            after_sequence_by_token=sequence_cutoffs,
        ):
            continue
        if replay_start_checkpoint_pair(
            reader,
            condition_id=market.condition_id,
            start_at_ms=selection.start_at_ms,
            session_id=selection.session_id,
        ) is not None:
            continue
        if _has_reconstructable_prestart_baselines(
            reader,
            market=market,
            start_at_ms=selection.start_at_ms,
            session=session,
            after_sequence_by_token=sequence_cutoffs,
        ):
            continue
        raise BacktestError(
            BacktestFailureReason.MISSING_MARKET_DATA,
            "selected market has no reconstructable two-token bootstrap: "
            f"{market.market_slug}",
        )


def _normalize_initial_interval(
    reader: RecordingReader,
    *,
    interval: _CleanInterval,
    session: RecordingSession,
    market_slugs: tuple[str, ...],
) -> _CleanInterval | None:
    if interval.start_at_ms != session.started_at_ms:
        return interval
    bounds = reader.event_bounds(
        start_at_ms=interval.start_at_ms,
        end_at_ms=interval.end_at_ms,
        session_id=session.session_id,
        market_slugs=market_slugs,
        allow_gaps=True,
    )
    if bounds is None:
        return None
    return _CleanInterval(bounds.start_at_ms, interval.end_at_ms)


def _prefixes_before_late_markets(
    reader: RecordingReader,
    *,
    interval: _CleanInterval,
    session: RecordingSession,
    market_slugs: tuple[str, ...],
) -> tuple[_CleanInterval, ...]:
    prefixes: set[_CleanInterval] = set()
    for market_slug in market_slugs:
        bounds = reader.event_bounds(
            start_at_ms=interval.start_at_ms,
            end_at_ms=interval.end_at_ms,
            session_id=session.session_id,
            market_slugs=(market_slug,),
            allow_gaps=True,
        )
        if bounds is not None and bounds.start_at_ms > interval.start_at_ms:
            prefixes.add(
                _CleanInterval(
                    interval.start_at_ms,
                    bounds.start_at_ms - 1,
                )
            )
    return tuple(prefixes)


def _suffixes_at_common_checkpoints(
    reader: RecordingReader,
    *,
    interval: _CleanInterval,
    session: RecordingSession,
    market_slugs: tuple[str, ...],
) -> tuple[_CleanInterval, ...]:
    suffixes: set[_CleanInterval] = set()
    markets = reader.markets_at(
        interval.end_at_ms,
        session_id=session.session_id,
        market_slugs=market_slugs,
        allow_gaps=True,
    )
    for market in markets:
        checkpoints = reader.checkpoint_pair_at_or_after(
            market.condition_id,
            interval.start_at_ms,
            end_at_ms=interval.end_at_ms,
            session_id=session.session_id,
            allow_gaps=True,
        )
        if (
            checkpoints is not None
            and checkpoints[0].observed_at_ms > interval.start_at_ms
        ):
            suffixes.add(
                _CleanInterval(
                    checkpoints[0].observed_at_ms,
                    interval.end_at_ms,
                )
            )
    return tuple(suffixes)


def _recovery_boundary_suffixes(
    reader: RecordingReader,
    *,
    interval: _CleanInterval,
    session: RecordingSession,
    market_slugs: tuple[str, ...],
) -> tuple[_CleanInterval, ...]:
    suffixes: set[_CleanInterval] = set()
    markets = reader.markets_at(
        interval.end_at_ms,
        session_id=session.session_id,
        market_slugs=market_slugs,
        allow_gaps=True,
    )
    for market in markets:
        sequence_cutoffs = _recovery_sequence_cutoffs(
            reader,
            market=market,
            start_at_ms=interval.start_at_ms,
            session=session,
        )
        if sequence_cutoffs is None:
            continue
        if replay_start_checkpoint_pair(
            reader,
            condition_id=market.condition_id,
            start_at_ms=interval.start_at_ms,
            session_id=session.session_id,
        ) is not None:
            continue
        if _has_reconstructable_prestart_baselines(
            reader,
            market=market,
            start_at_ms=interval.start_at_ms,
            session=session,
            after_sequence_by_token=sequence_cutoffs,
        ):
            continue
        checkpoint_pair = reader.checkpoint_pair_at_or_after(
            market.condition_id,
            interval.start_at_ms,
            end_at_ms=interval.end_at_ms,
            session_id=session.session_id,
            allow_gaps=True,
        )
        baseline_at_ms = reader.first_complete_baseline_pair_at_or_after(
            market,
            start_at_ms=interval.start_at_ms,
            end_at_ms=interval.end_at_ms,
            session_id=session.session_id,
            after_sequence_by_token=sequence_cutoffs,
        )
        boundaries = [
            boundary
            for boundary in (
                None
                if checkpoint_pair is None
                else checkpoint_pair[0].observed_at_ms,
                baseline_at_ms,
            )
            if boundary is not None
        ]
        if boundaries and (boundary_ms := min(boundaries)) > interval.start_at_ms:
            suffixes.add(_CleanInterval(boundary_ms, interval.end_at_ms))
    return tuple(suffixes)


def _has_reconstructable_prestart_baselines(
    reader: RecordingReader,
    *,
    market: MarketMetadataPayload,
    start_at_ms: int,
    session: RecordingSession,
    after_sequence_by_token: dict[str, int] | None = None,
) -> bool:
    prime_at_ms = start_at_ms - 1
    scan_start_ms = clean_scan_start_after_gaps(
        reader,
        session=session,
        condition_id=market.condition_id,
        through_ms=prime_at_ms,
    )
    return scan_start_ms is not None and reader.has_complete_baseline_pair(
        market,
        start_at_ms=scan_start_ms,
        end_at_ms=prime_at_ms,
        session_id=session.session_id,
        after_sequence_by_token=after_sequence_by_token,
    )


def _recovery_sequence_cutoffs(
    reader: RecordingReader,
    *,
    market: MarketMetadataPayload,
    start_at_ms: int,
    session: RecordingSession,
) -> dict[str, int] | None:
    return recovery_sequence_cutoffs(
        recovery_token_boundaries(
            reader,
            session=session,
            market=market,
            boundary_at_ms=start_at_ms,
        )
    )


def _clean_intervals(
    session_start_ms: int,
    session_end_ms: int,
    gaps: tuple[CoverageGapRecord, ...],
) -> tuple[_CleanInterval, ...]:
    cursor = session_start_ms
    intervals: list[_CleanInterval] = []
    for record in sorted(gaps, key=lambda value: value.gap.started_at_ms):
        gap = record.gap
        if (
            gap.ended_at_ms is not None
            and gap.ended_at_ms == gap.started_at_ms
        ):
            continue
        if gap.started_at_ms > session_end_ms:
            break
        if gap.ended_at_ms is not None and gap.ended_at_ms <= cursor:
            continue
        gap_start = max(session_start_ms, gap.started_at_ms)
        if gap_start > cursor:
            intervals.append(_CleanInterval(cursor, gap_start - 1))
        gap_end = (
            session_end_ms + 1
            if gap.ended_at_ms is None
            else min(session_end_ms + 1, gap.ended_at_ms)
        )
        cursor = max(cursor, gap_end)
        if cursor > session_end_ms:
            break
    if cursor <= session_end_ms:
        intervals.append(_CleanInterval(cursor, session_end_ms))
    return tuple(intervals)
