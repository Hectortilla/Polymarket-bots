from __future__ import annotations

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestSelection,
)
from polybot.backtesting.selection.bootstrap import ReplayBootstrap
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.book import BookBaselinePayload


class SelectionCoverage:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def validate_events(
        self,
        selection: BacktestSelection,
    ) -> None:
        """Semantically validate selected events and their replay bootstrap."""

        allow_gaps = selection.gap_policy.allows_gaps

        baseline_tokens: dict[tuple[str, int], set[str]] = {}
        for event in self._reader.iter_events(
            start_at_ms=selection.start_at_ms,
            end_at_ms=selection.end_at_ms,
            session_id=selection.session_id,
            market_slugs=selection.market_slugs,
            allow_gaps=allow_gaps,
        ):
            if not isinstance(event.payload, BookBaselinePayload):
                continue
            condition_id = (
                None if event.identity is None else event.identity.condition_id
            )
            if condition_id is None:
                raise BacktestError(
                    BacktestFailureReason.MISSING_MARKET_DATA,
                    f"book baseline event {event.sequence} has no market identity",
                )
            baseline_tokens.setdefault(
                (condition_id, event.subscription_generation),
                set(),
            ).add(event.payload.token_id)

        markets = self._reader.markets_at(
            selection.end_at_ms,
            session_id=selection.session_id,
            market_slugs=selection.market_slugs,
            allow_gaps=allow_gaps,
        )
        for market in markets:
            required_tokens = {outcome.token_id for outcome in market.outcomes}
            has_complete_baseline = any(
                condition_id == market.condition_id and required_tokens.issubset(tokens)
                for (condition_id, _), tokens in baseline_tokens.items()
            )
            ReplayBootstrap(self._reader).require_market(
                selection,
                market,
                has_complete_baseline=has_complete_baseline,
            )

    def validate_indexes(
        self,
        selection: BacktestSelection,
    ) -> None:
        """Validate indexed bootstrap coverage without scanning all replay events."""

        allow_gaps = selection.gap_policy.allows_gaps

        markets = self._reader.markets_at(
            selection.end_at_ms,
            session_id=selection.session_id,
            market_slugs=selection.market_slugs,
            allow_gaps=allow_gaps,
        )
        for market in markets:
            ReplayBootstrap(self._reader).require_market(
                selection,
                market,
                has_complete_baseline=self._reader.has_complete_baseline_pair(
                    market,
                    start_at_ms=selection.start_at_ms,
                    end_at_ms=selection.end_at_ms,
                    session_id=selection.session_id,
                ),
            )
