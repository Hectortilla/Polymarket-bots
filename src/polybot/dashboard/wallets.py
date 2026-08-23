"""Followed-wallet state shared by dashboard renderers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from polybot.framework.wallets import normalize_wallet_address

from .contracts import (
    MAX_WALLET_TIMELINE_EVENTS,
    WalletChartPoint,
    format_market_label,
)

WALLET_NOTIONAL_TIER_COUNT = 3

if TYPE_CHECKING:
    from polybot.framework.events import Side
    from polybot.framework.events.wallet_trades import WalletTradeEvent


@dataclass(slots=True)
class WalletTimelineEvent:
    source_key: str
    wallet: str
    trade_timestamp_ms: int
    side: Side
    notional: Decimal
    market_label: str
    accepted: bool | None = None

    def chart_point(self) -> WalletChartPoint:
        return WalletChartPoint(
            source_key=self.source_key,
            wallet=self.wallet,
            trade_timestamp_ms=self.trade_timestamp_ms,
            side=self.side,
            notional=self.notional,
            market_label=self.market_label,
            accepted=self.accepted,
        )


@dataclass(slots=True)
class DashboardWallets:
    wallet_lanes: deque[str] = field(default_factory=deque)
    wallet_timeline: deque[WalletTimelineEvent] = field(default_factory=deque)
    wallet_timeline_by_source: dict[str, WalletTimelineEvent] = field(
        default_factory=dict
    )

    def record_trade(self, trade: WalletTradeEvent) -> WalletTimelineEvent:
        self.activate_lane(trade.wallet)
        point = wallet_chart_point(trade)
        timeline_event = WalletTimelineEvent(
            source_key=point.source_key,
            wallet=point.wallet,
            trade_timestamp_ms=point.trade_timestamp_ms,
            side=point.side,
            notional=point.notional,
            market_label=point.market_label,
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

    def _trim_timeline(self) -> None:
        while len(self.wallet_timeline) > MAX_WALLET_TIMELINE_EVENTS:
            expired = self.wallet_timeline.popleft()
            if self.wallet_timeline_by_source.get(expired.source_key) is expired:
                self.wallet_timeline_by_source.pop(expired.source_key, None)


def wallet_market_label(trade: WalletTradeEvent) -> str:
    return format_market_label(trade.token_id, trade.market_slug, trade.outcome)


def wallet_chart_point(
    trade: WalletTradeEvent,
    *,
    accepted: bool | None = None,
) -> WalletChartPoint:
    return WalletChartPoint(
        source_key=trade.source_key,
        wallet=normalize_wallet_address(trade.wallet),
        trade_timestamp_ms=trade.trade_timestamp_ms,
        side=trade.side,
        notional=trade.price * trade.size,
        market_label=wallet_market_label(trade),
        accepted=accepted,
    )


def wallet_bucket_index(
    timestamp_ms: int,
    start_ms: int,
    end_ms: int,
    columns: int,
) -> int:
    return min(
        columns - 1,
        (timestamp_ms - start_ms) * columns // (end_ms - start_ms),
    )


def wallet_notional_tier(notional: Decimal, maximum_notional: Decimal) -> int:
    weighted_notional = notional * WALLET_NOTIONAL_TIER_COUNT
    if maximum_notional <= 0 or weighted_notional <= maximum_notional:
        return 1
    return (
        2
        if weighted_notional
        <= maximum_notional * (WALLET_NOTIONAL_TIER_COUNT - 1)
        else 3
    )
