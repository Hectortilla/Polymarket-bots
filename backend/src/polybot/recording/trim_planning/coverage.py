from __future__ import annotations

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestSelection,
)
from polybot.backtesting.selection.bootstrap import ReplayBootstrap
from polybot.recording.archive.models import RecordingSession
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.trim_recovery import TrimRecovery
from polybot.recording.trim_recovery.boundaries import recovery_sequence_cutoffs


class TrimCoverage:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def retained_market_slugs(
        self,
        *,
        selection: BacktestSelection,
        session: RecordingSession,
    ) -> tuple[str, ...]:
        """Keep market state needed at the boundary or observed inside the interval."""

        markets_at_start = (
            ()
            if selection.start_at_ms == 0
            else self._reader.markets_at(
                selection.start_at_ms - 1,
                session_id=session.session_id,
                market_slugs=selection.market_slugs,
                allow_gaps=True,
            )
        )
        known_at_start = {market.market_slug for market in markets_at_start}
        active_at_start = {
            market.market_slug for market in markets_at_start if not market.resolved
        }
        introduced_in_range = (
            set(
                self._reader.market_slugs_with_metadata_revisions(
                    start_at_ms=selection.start_at_ms,
                    end_at_ms=selection.end_at_ms,
                    session_id=session.session_id,
                    market_slugs=selection.market_slugs,
                    allow_gaps=True,
                )
            )
            - known_at_start
        )
        # A resolved market can still receive a metadata refresh after its resolution.
        # It has no replayable state at the new boundary, so retaining that refresh
        # would make the trimmed archive fail its own baseline validation.
        return tuple(sorted(active_at_start | introduced_in_range))

    def validate(
        self,
        selection: BacktestSelection,
        session: RecordingSession,
    ) -> None:
        markets = self._reader.markets_at(
            selection.end_at_ms,
            session_id=selection.session_id,
            market_slugs=selection.market_slugs,
        )
        for market in markets:
            sequence_cutoffs = self.recovery_sequence_cutoffs(
                market=market,
                start_at_ms=selection.start_at_ms,
                session=session,
            )
            if self._reader.has_complete_baseline_pair(
                market,
                start_at_ms=selection.start_at_ms,
                end_at_ms=selection.end_at_ms,
                session_id=selection.session_id,
                after_sequence_by_token=sequence_cutoffs,
            ):
                continue
            if (
                ReplayBootstrap(self._reader).checkpoint_pair(
                    condition_id=market.condition_id,
                    start_at_ms=selection.start_at_ms,
                    session_id=selection.session_id,
                )
                is not None
            ):
                continue
            if self.has_reconstructable_prestart_baselines(
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

    def has_reconstructable_prestart_baselines(
        self,
        *,
        market: MarketMetadataPayload,
        start_at_ms: int,
        session: RecordingSession,
        after_sequence_by_token: dict[str, int] | None = None,
    ) -> bool:
        prime_at_ms = start_at_ms - 1
        scan_start_ms = TrimRecovery(self._reader).clean_scan_start(
            session=session,
            condition_id=market.condition_id,
            through_ms=prime_at_ms,
        )
        return scan_start_ms is not None and self._reader.has_complete_baseline_pair(
            market,
            start_at_ms=scan_start_ms,
            end_at_ms=prime_at_ms,
            session_id=session.session_id,
            after_sequence_by_token=after_sequence_by_token,
        )

    def recovery_sequence_cutoffs(
        self,
        *,
        market: MarketMetadataPayload,
        start_at_ms: int,
        session: RecordingSession,
    ) -> dict[str, int] | None:
        return recovery_sequence_cutoffs(
            TrimRecovery(self._reader).token_boundaries(
                session=session,
                market=market,
                boundary_at_ms=start_at_ms,
            )
        )
