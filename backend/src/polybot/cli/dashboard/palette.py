"""Shared visual identity for each displayed market series."""

from __future__ import annotations

import asciichartpy

from polybot.framework.events import Side

SERIES_PALETTE: tuple[tuple[str, str], ...] = (
    (asciichartpy.cyan, "cyan"),
    (asciichartpy.magenta, "magenta"),
    (asciichartpy.yellow, "yellow"),
    (asciichartpy.green, "green"),
    (asciichartpy.lightblue, "bright_blue"),
    (asciichartpy.lightred, "bright_red"),
    (asciichartpy.lightcyan, "bright_cyan"),
    (asciichartpy.white, "white"),
    ("\033[38;5;208m", "color(208)"),
    ("\033[38;5;129m", "color(129)"),
    ("\033[38;5;205m", "color(205)"),
    ("\033[38;5;37m", "color(37)"),
    ("\033[38;5;118m", "color(118)"),
    ("\033[38;5;220m", "color(220)"),
    ("\033[38;5;203m", "color(203)"),
    ("\033[38;5;99m", "color(99)"),
    ("\033[38;5;44m", "color(44)"),
    ("\033[38;5;209m", "color(209)"),
    ("\033[38;5;48m", "color(48)"),
    ("\033[38;5;250m", "color(250)"),
)

SIDE_CHART_COLORS = {
    Side.BUY: asciichartpy.lightgreen,
    Side.SELL: asciichartpy.red,
}
SIDE_TEXT_STYLES = {
    Side.BUY: "green",
    Side.SELL: "red",
}


def side_chart_color(side: Side) -> str:
    return SIDE_CHART_COLORS[side]


def side_text_style(side: Side, *, bold: bool = False) -> str:
    style = SIDE_TEXT_STYLES[side]
    return f"bold {style}" if bold else style
