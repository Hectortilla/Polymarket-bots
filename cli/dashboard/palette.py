"""Shared visual identity for each displayed market series."""

from __future__ import annotations

import asciichartpy

SERIES_PALETTE: tuple[tuple[str, str], ...] = (
    (asciichartpy.cyan, "cyan"),
    (asciichartpy.magenta, "magenta"),
    (asciichartpy.yellow, "yellow"),
    (asciichartpy.green, "green"),
)
