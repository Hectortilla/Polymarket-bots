from __future__ import annotations

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestSelection,
)
from polybot.backtesting.coverage_selection import gaps_affecting_markets
from polybot.recording.archive.errors import ArchiveCoverageError
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.records import BookCheckpoint


class ReplayBootstrap:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def require_market(
        self,
        selection: BacktestSelection,
        market: MarketMetadataPayload,
        *,
        has_complete_baseline: bool,
    ) -> None:
        if has_complete_baseline:
            return
        checkpoint_pair = self.checkpoint_pair(
            condition_id=market.condition_id,
            start_at_ms=selection.start_at_ms,
            session_id=selection.session_id,
            allow_pre_gap_checkpoint=(
                selection.gap_policy.allows_gaps
                and self.starts_in_market_gap(selection, market)
            ),
        )
        if checkpoint_pair is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                "selected market has no complete two-token baseline or checkpoint: "
                f"{market.market_slug}",
            )

    def checkpoint_pair(
        self,
        *,
        condition_id: str,
        start_at_ms: int,
        session_id: int,
        allow_pre_gap_checkpoint: bool = False,
    ) -> tuple[BookCheckpoint, BookCheckpoint] | None:
        """Find a clean pair, optionally retained only as active-gap evidence."""

        prime_at_ms = start_at_ms - 1
        if prime_at_ms >= 0:
            try:
                checkpoints = self._reader.checkpoint_pair_before(
                    condition_id,
                    prime_at_ms,
                    session_id=session_id,
                    allow_gaps=allow_pre_gap_checkpoint,
                )
            except ArchiveCoverageError:
                checkpoints = None
            if checkpoints is not None:
                return checkpoints
        if allow_pre_gap_checkpoint:
            return None
        return self._reader.checkpoint_pair_at(
            condition_id,
            start_at_ms,
            session_id=session_id,
        )

    def starts_in_market_gap(
        self,
        selection: BacktestSelection,
        market: MarketMetadataPayload,
    ) -> bool:
        """Return whether an affecting half-open gap contains the selected start."""

        records = self._reader.coverage_gaps(
            start_at_ms=selection.start_at_ms,
            end_at_ms=selection.start_at_ms,
            session_id=selection.session_id,
        )
        return bool(gaps_affecting_markets(records, (market,)))
