"""Followed-wallet trade-time timeline rendering."""

from __future__ import annotations

from collections import defaultdict, deque
from decimal import Decimal

from rich.console import Group
from rich.text import Text

from polybot.framework.events import Side

from .layout import WALLET_SUMMARY_MIN_WIDTH, primary_chart_available_height
from .palette import side_text_style
from .state import DashboardState
from .wallet_state import WalletTimelineEvent

WALLET_LANE_LABEL_WIDTH = 13
WALLET_LANE_SUMMARY_WIDTH = 21


def wallet_lane_capacity(width: int, height: int) -> int:
    return max(1, min(12, primary_chart_available_height(width, height) - 4))


def wallet_timeline(state: DashboardState, width: int, height: int) -> Group:
    capacity = wallet_lane_capacity(width, height)
    lane_count = len(state.wallet_lanes)
    maximum_page = max(0, (lane_count - 1) // capacity)
    page = min(state.wallet_page, maximum_page)
    lanes = list(state.wallet_lanes)[page * capacity : (page + 1) * capacity]
    columns = wallet_timeline_columns(state, width)
    visible_range = state.visible_epoch_seconds_range(width)
    header = Text(
        "green buy · red sell · yellow mixed · ·/●/◆ relative notional · "
        "dim skipped · v market · j/k wallets",
        style="bright_cyan",
    )
    if not lanes:
        return Group(
            header, Text("No followed wallets configured or detected", style="dim")
        )
    if visible_range is None:
        return Group(header, Text("Waiting for a dashboard time window", style="dim"))
    start, end = visible_range
    events_by_lane = wallet_timeline_buckets(
        state.wallet_timeline, lanes, start, end, columns
    )
    bucket_notionals = [
        sum(event.notional for event in events)
        for lane_buckets in events_by_lane.values()
        for events in lane_buckets.values()
    ]
    maximum_notional = max(bucket_notionals, default=Decimal("0"))
    page_label = f" wallets {page + 1}/{maximum_page + 1}" if maximum_page else ""
    rows: list[Text] = [
        Text(f"Trade-time event timeline{page_label}", style="bold white")
    ]
    for wallet in lanes:
        buckets = events_by_lane.get(wallet, {})
        row = Text(f"{short_wallet(wallet):<{WALLET_LANE_LABEL_WIDTH}}", style="cyan")
        for bucket in range(columns):
            glyph, style = wallet_bucket_glyph(
                buckets.get(bucket, ()), maximum_notional
            )
            row.append(glyph, style=style)
        if width >= WALLET_SUMMARY_MIN_WIDTH:
            row.append(wallet_lane_summary(buckets), style="dim")
        rows.append(row)
    return Group(header, *rows)


def wallet_timeline_columns(state: DashboardState, width: int) -> int:
    summary_width = (
        WALLET_LANE_SUMMARY_WIDTH if width >= WALLET_SUMMARY_MIN_WIDTH else 0
    )
    return max(
        12, state.chart_display_points(width) - WALLET_LANE_LABEL_WIDTH - summary_width
    )


def wallet_timeline_buckets(
    events: deque[WalletTimelineEvent],
    lanes: list[str],
    start_epoch_seconds: float,
    end_epoch_seconds: float,
    columns: int,
) -> dict[str, dict[int, list[WalletTimelineEvent]]]:
    events_by_wallet_and_bucket: dict[
        str, dict[int, list[WalletTimelineEvent]]
    ] = defaultdict(lambda: defaultdict(list))
    lane_set = set(lanes)
    if end_epoch_seconds <= start_epoch_seconds:
        return events_by_wallet_and_bucket
    span_seconds = end_epoch_seconds - start_epoch_seconds
    for event in events:
        timestamp_epoch_seconds = event.trade_timestamp_ms / 1_000
        if (
            event.wallet not in lane_set
            or timestamp_epoch_seconds < start_epoch_seconds
            or timestamp_epoch_seconds > end_epoch_seconds
        ):
            continue
        bucket = _timeline_bucket_for_timestamp(
            timestamp_epoch_seconds,
            start_epoch_seconds,
            span_seconds,
            columns,
        )
        events_by_wallet_and_bucket[event.wallet][bucket].append(event)
    return events_by_wallet_and_bucket


def _timeline_bucket_for_timestamp(
    timestamp_epoch_seconds: float,
    start_epoch_seconds: float,
    span_seconds: float,
    columns: int,
) -> int:
    return min(
        columns - 1,
        int(
            (timestamp_epoch_seconds - start_epoch_seconds)
            / span_seconds
            * columns
        ),
    )


def wallet_bucket_glyph(
    events: list[WalletTimelineEvent] | tuple[WalletTimelineEvent, ...],
    maximum_notional: Decimal,
) -> tuple[str, str]:
    if not events:
        return " ", ""
    sides = {event.side for event in events}
    notional = sum((event.notional for event in events), Decimal("0"))
    if maximum_notional <= 0 or notional <= maximum_notional / 3:
        glyph = "·"
    elif notional <= maximum_notional * 2 / 3:
        glyph = "●"
    else:
        glyph = "◆"
    style = "yellow" if len(sides) > 1 else side_text_style(next(iter(sides)))
    if all(event.accepted is False for event in events):
        style = f"dim {style}"
    elif glyph == "◆":
        style = f"bold {style}"
    return glyph, style


def wallet_lane_summary(buckets: dict[int, list[WalletTimelineEvent]]) -> str:
    events = [event for bucket_events in buckets.values() for event in bucket_events]
    buys = sum(event.side is Side.BUY for event in events)
    sells = len(events) - buys
    notional = sum((event.notional for event in events), Decimal("0"))
    return f" B{buys} S{sells} ${notional:.0f}"


def short_wallet(wallet: str) -> str:
    return wallet if len(wallet) <= 12 else f"{wallet[:6]}…{wallet[-4:]}"
