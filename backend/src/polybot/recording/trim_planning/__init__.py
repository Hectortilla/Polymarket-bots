from __future__ import annotations

from pathlib import Path

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestOptions,
)
from polybot.backtesting.selection import ReplaySelectionResolver
from polybot.recording.archive.errors import ArchiveFormatError, RecordingArchiveError
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.trim_contracts import RecordingTrimError, RecordingTrimPlan
from polybot.recording.trim_planning.candidates import TrimCandidates
from polybot.recording.trim_planning.coverage import TrimCoverage
from polybot.recording.trim_planning.intervals import (
    CleanInterval,
    candidate_sort_key,
    clean_intervals,
)


class RecordingTrimPlanner:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def plan(
        self,
        *,
        archive_path: Path,
        session_id: int | None,
    ) -> RecordingTrimPlan:
        """Choose the longest all-market clean interval in one selected session."""

        sessions = self._reader.sessions()
        if session_id is None and len(sessions) > 1:
            available_ids = ", ".join(str(session.session_id) for session in sessions)
            raise ArchiveFormatError(
                "recording archive requires an explicit --session ID; "
                f"available session IDs: {available_ids}"
            )
        session = self._reader.select_session(session_id)
        session_end = ReplaySelectionResolver(self._reader).session_end(session)
        if session_end is None:
            raise RecordingTrimError(
                f"recording session {session.session_id} has no replayable boundary"
            )
        markets = self._reader.markets_at(
            session_end,
            session_id=session.session_id,
            allow_gaps=True,
        )
        market_slugs = tuple(sorted({market.market_slug for market in markets}))
        if not market_slugs:
            raise RecordingTrimError(
                f"recording session {session.session_id} contains no market data"
            )
        affecting_gaps = self._reader.coverage_gaps(
            start_at_ms=session.started_at_ms,
            end_at_ms=session_end,
            session_id=session.session_id,
            market_slugs=market_slugs,
        )
        raw_intervals_list: list[CleanInterval] = []
        for interval in clean_intervals(
            session.started_at_ms,
            session_end,
            affecting_gaps,
        ):
            normalized = TrimCandidates(self._reader).normalize_initial_interval(
                interval=interval,
                session=session,
                market_slugs=market_slugs,
            )
            if normalized is not None:
                raw_intervals_list.append(normalized)
        raw_intervals = tuple(raw_intervals_list)
        candidates = set(raw_intervals)
        expanded_intervals: set[CleanInterval] = set()
        failures: list[str] = []
        while candidates:
            candidate = min(candidates, key=candidate_sort_key)
            candidates.remove(candidate)
            recovery_suffixes = TrimCandidates(self._reader).recovery_boundary_suffixes(
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
                selection = ReplaySelectionResolver(self._reader).resolve(
                    session, options
                )
                retained_market_slugs = TrimCoverage(
                    self._reader
                ).retained_market_slugs(
                    selection=selection,
                    session=session,
                )
                if not retained_market_slugs:
                    raise BacktestError(
                        BacktestFailureReason.EMPTY_SELECTION,
                        "selected recording range contains no active market data",
                    )
                selection = ReplaySelectionResolver(self._reader).resolve(
                    session,
                    BacktestOptions(
                        archive_path=archive_path,
                        session_id=session.session_id,
                        start_at_ms=candidate.start_at_ms,
                        end_at_ms=candidate.end_at_ms,
                        market_slugs=retained_market_slugs,
                    ),
                )
                TrimCoverage(self._reader).validate(selection, session)
            except (BacktestError, RecordingArchiveError, ValueError) as error:
                failures.append(str(error))
                first_expansion = candidate not in expanded_intervals
                if first_expansion:
                    expanded_intervals.add(candidate)
                    candidates.update(
                        TrimCandidates(self._reader).suffixes_at_common_checkpoints(
                            interval=candidate,
                            session=session,
                            market_slugs=market_slugs,
                        )
                    )
                if candidate in raw_intervals and first_expansion:
                    candidates.update(
                        TrimCandidates(self._reader).prefixes_before_late_markets(
                            interval=candidate,
                            session=session,
                            market_slugs=market_slugs,
                        )
                    )
                continue
            return RecordingTrimPlan(
                archive_path=archive_path,
                target_identity=self._reader.target_identity,
                source_session=session,
                start_at_ms=selection.start_at_ms,
                end_at_ms=selection.end_at_ms,
                market_slugs=selection.market_slugs,
                source_event_count=self._reader.event_count(
                    start_at_ms=selection.start_at_ms,
                    end_at_ms=selection.end_at_ms,
                    session_id=session.session_id,
                    market_slugs=selection.market_slugs,
                ),
                source_gap_count=len(
                    self._reader.coverage_gaps(session_id=session.session_id)
                ),
                source_size_bytes=archive_path.stat().st_size,
            )

        detail = "" if not failures else f": {failures[0]}"
        raise RecordingTrimError(
            f"recording has no gap-free interval that passes replay validation{detail}"
        )
