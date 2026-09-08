"""Shared terminal-dashboard layout dimensions."""

from __future__ import annotations

DASHBOARD_NARROW_WIDTH = 110
DASHBOARD_STATUS_HEIGHT = 5
WALLET_VALUE_CHART_MIN_HEIGHT = 30
WALLET_VALUE_CHART_HEIGHT = 8
WALLET_SUMMARY_MIN_WIDTH = 155


def chart_panel_width(width: int) -> int:
    return width * 2 // 3 if width >= DASHBOARD_NARROW_WIDTH else width


def primary_chart_available_height(width: int, height: int) -> int:
    available_height = height - DASHBOARD_STATUS_HEIGHT
    if width < DASHBOARD_NARROW_WIDTH:
        available_height = available_height * 2 // 3
    if height >= WALLET_VALUE_CHART_MIN_HEIGHT:
        available_height -= WALLET_VALUE_CHART_HEIGHT
    return available_height
