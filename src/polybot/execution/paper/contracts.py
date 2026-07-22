"""Stable paper-broker order and rejection contracts."""

from __future__ import annotations


PAPER_ORDER_ID_PREFIX = "paper-"
NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE = "no book depth remained within the slippage cap"
BOOK_UNAVAILABLE_MESSAGE = "fill-time book lookup failed"
BOOK_MISMATCH_MESSAGE = "fill-time book did not match the requested order"
BOOK_STALE_MESSAGE = "fill-time book was stale"
BAD_BOOK_LEVEL_MESSAGE = "fill-time book contained invalid levels"
BOOK_FUTURE_DATED_MESSAGE = "fill-time book was future-dated"
BOOK_CROSSED_MESSAGE = "fill-time book was crossed"
BACKTEST_DATA_EXHAUSTED_MESSAGE = (
    "recorded market data ended before simulated order latency completed"
)
BACKTEST_COVERAGE_GAP_MESSAGE = (
    "recorded market coverage was unavailable during simulated order latency"
)
