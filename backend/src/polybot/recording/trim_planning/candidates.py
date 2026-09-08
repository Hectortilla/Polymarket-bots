from __future__ import annotations

from polybot.backtesting.selection.bootstrap import ReplayBootstrap
from polybot.recording.archive.models import RecordingSession
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.trim_planning.coverage import TrimCoverage
from polybot.recording.trim_planning.intervals import CleanInterval


class TrimCandidates:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def normalize_initial_interval(
        self,
        *,
        interval: CleanInterval,
        session: RecordingSession,
        market_slugs: tuple[str, ...],
    ) -> CleanInterval | None:
        if interval.start_at_ms != session.started_at_ms:
            return interval
        bounds = self._reader.event_bounds(
            start_at_ms=interval.start_at_ms,
            end_at_ms=interval.end_at_ms,
            session_id=session.session_id,
            market_slugs=market_slugs,
            allow_gaps=True,
        )
        if bounds is None:
            return None
        return CleanInterval(bounds.start_at_ms, interval.end_at_ms)

    def prefixes_before_late_markets(
        self,
        *,
        interval: CleanInterval,
        session: RecordingSession,
        market_slugs: tuple[str, ...],
    ) -> tuple[CleanInterval, ...]:
        prefixes: set[CleanInterval] = set()
        for market_slug in market_slugs:
            bounds = self._reader.event_bounds(
                start_at_ms=interval.start_at_ms,
                end_at_ms=interval.end_at_ms,
                session_id=session.session_id,
                market_slugs=(market_slug,),
                allow_gaps=True,
            )
            if bounds is not None and bounds.start_at_ms > interval.start_at_ms:
                prefixes.add(
                    CleanInterval(
                        interval.start_at_ms,
                        bounds.start_at_ms - 1,
                    )
                )
        return tuple(prefixes)

    def suffixes_at_common_checkpoints(
        self,
        *,
        interval: CleanInterval,
        session: RecordingSession,
        market_slugs: tuple[str, ...],
    ) -> tuple[CleanInterval, ...]:
        suffixes: set[CleanInterval] = set()
        markets = self._reader.markets_at(
            interval.end_at_ms,
            session_id=session.session_id,
            market_slugs=market_slugs,
            allow_gaps=True,
        )
        for market in markets:
            checkpoints = self._reader.checkpoint_pair_at_or_after(
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
                    CleanInterval(
                        checkpoints[0].observed_at_ms,
                        interval.end_at_ms,
                    )
                )
        return tuple(suffixes)

    def recovery_boundary_suffixes(
        self,
        *,
        interval: CleanInterval,
        session: RecordingSession,
        market_slugs: tuple[str, ...],
    ) -> tuple[CleanInterval, ...]:
        suffixes: set[CleanInterval] = set()
        markets = self._reader.markets_at(
            interval.end_at_ms,
            session_id=session.session_id,
            market_slugs=market_slugs,
            allow_gaps=True,
        )
        for market in markets:
            sequence_cutoffs = TrimCoverage(self._reader).recovery_sequence_cutoffs(
                market=market,
                start_at_ms=interval.start_at_ms,
                session=session,
            )
            if sequence_cutoffs is None:
                continue
            if (
                ReplayBootstrap(self._reader).checkpoint_pair(
                    condition_id=market.condition_id,
                    start_at_ms=interval.start_at_ms,
                    session_id=session.session_id,
                )
                is not None
            ):
                continue
            if TrimCoverage(self._reader).has_reconstructable_prestart_baselines(
                market=market,
                start_at_ms=interval.start_at_ms,
                session=session,
                after_sequence_by_token=sequence_cutoffs,
            ):
                continue
            checkpoint_pair = self._reader.checkpoint_pair_at_or_after(
                market.condition_id,
                interval.start_at_ms,
                end_at_ms=interval.end_at_ms,
                session_id=session.session_id,
                allow_gaps=True,
            )
            baseline_at_ms = self._reader.first_complete_baseline_pair_at_or_after(
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
                suffixes.add(CleanInterval(boundary_ms, interval.end_at_ms))
        return tuple(suffixes)
