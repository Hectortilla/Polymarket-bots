"""Dashboard-only projection helpers for followed-wallet activity."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal

from polybot.framework.events import Side
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.wallets import normalize_wallet_address

from .token_labels import format_market_label

MAX_WALLET_TIMELINE_EVENTS = 5_000


@dataclass(slots=True)
class WalletTimelineEvent:
    source_key: str
    wallet: str
    trade_timestamp_ms: int
    side: Side
    notional: Decimal
    market_label: str
    accepted: bool | None = None


@dataclass(slots=True)
class DashboardWalletTimeline:
    """Followed-wallet lanes, pagination, and recent activity events."""

    wallet_lanes: deque[str] = field(default_factory=deque)
    wallet_timeline: deque[WalletTimelineEvent] = field(default_factory=deque)
    wallet_timeline_by_source: dict[str, WalletTimelineEvent] = field(
        default_factory=dict
    )
    wallet_page: int = 0

    def record_trade(self, trade: WalletTradeEvent) -> WalletTimelineEvent:
        self.activate_lane(trade.wallet)
        timeline_event = WalletTimelineEvent(
            source_key=trade.source_key,
            wallet=normalize_wallet_address(trade.wallet),
            trade_timestamp_ms=trade.trade_timestamp_ms,
            side=trade.side,
            notional=trade.price * trade.size,
            market_label=wallet_market_label(trade),
        )
        self.wallet_timeline.append(timeline_event)
        self.wallet_timeline_by_source[trade.source_key] = timeline_event
        self._trim_timeline()
        return timeline_event

    def mark_dispatch(self, source_key: str, *, accepted: bool) -> None:
        timeline_event = self.wallet_timeline_by_source.get(source_key)
        if timeline_event is not None:
            timeline_event.accepted = accepted

    def set_lanes(self, wallets: tuple[str, ...]) -> None:
        for wallet in wallets:
            self.activate_lane(wallet)

    def activate_lane(self, wallet: str) -> None:
        normalized = normalize_wallet_address(wallet)
        if normalized not in self.wallet_lanes:
            self.wallet_lanes.append(normalized)

    def reset_page(self) -> None:
        self.wallet_page = 0

    def page(self, direction: int, lanes_per_page: int) -> bool:
        if lanes_per_page <= 0:
            return False
        maximum = max(0, (len(self.wallet_lanes) - 1) // lanes_per_page)
        updated = min(maximum, max(0, self.wallet_page + direction))
        if updated == self.wallet_page:
            return False
        self.wallet_page = updated
        return True

    def revalidate_page(self, lanes_per_page: int) -> bool:
        if lanes_per_page <= 0:
            return False
        maximum = max(0, (len(self.wallet_lanes) - 1) // lanes_per_page)
        if self.wallet_page <= maximum:
            return False
        self.wallet_page = maximum
        return True

    def _trim_timeline(self) -> None:
        while len(self.wallet_timeline) > MAX_WALLET_TIMELINE_EVENTS:
            expired = self.wallet_timeline.popleft()
            if self.wallet_timeline_by_source.get(expired.source_key) is expired:
                self.wallet_timeline_by_source.pop(expired.source_key, None)


def wallet_market_label(trade: WalletTradeEvent) -> str:
    return format_market_label(trade.token_id, trade.market_slug, trade.outcome)
