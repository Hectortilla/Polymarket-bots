"""Terminal-only market ticker behavior."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from polybot.dashboard.contracts import format_token_label
from polybot.dashboard.markets import DashboardMarkets as SharedDashboardMarkets
from polybot.framework.events.books import BookSnapshot


MARKET_TICKER_INTERVAL_SECONDS = 1


@dataclass(slots=True)
class DashboardMarkets(SharedDashboardMarkets):
    market_ticker_at_monotonic_seconds: dict[str, float] = field(default_factory=dict)

    def market_ticker_message(
        self,
        book: BookSnapshot,
        occurred_at_monotonic_seconds: float,
    ) -> str | None:
        midpoint = book.midpoint()
        previous_ticker_at = self.market_ticker_at_monotonic_seconds.get(book.token_id)
        if midpoint is None or (
            previous_ticker_at is not None
            and occurred_at_monotonic_seconds - previous_ticker_at
            < MARKET_TICKER_INTERVAL_SECONDS
        ):
            return None
        self.market_ticker_at_monotonic_seconds[book.token_id] = (
            occurred_at_monotonic_seconds
        )
        return f"MARKET {format_token_label(book.token_id)} mid {midpoint:.4f}"

    def settle(
        self, *, condition_id: str, token_ids: Iterable[str]
    ) -> tuple[str, ...]:
        settled_token_ids = SharedDashboardMarkets.settle(
            self,
            condition_id=condition_id,
            token_ids=token_ids,
        )
        for token_id in settled_token_ids:
            self.market_ticker_at_monotonic_seconds.pop(token_id, None)
        return settled_token_ids
