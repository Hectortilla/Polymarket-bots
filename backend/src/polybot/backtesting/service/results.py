"""Deterministic identifiers and paths for backtest artifacts."""

from __future__ import annotations

import time
from pathlib import Path

DEFAULT_BACKTEST_RESULTS_DIR = Path("data/backtests")


def default_results_dir(archive_path: Path, bot_name: str) -> Path:
    """Build a collision-resistant, readable default artifact directory."""
    safe_name = (
        "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in bot_name
        ).strip("-")
        or "bot"
    )
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    suffix = time.time_ns() % 1_000_000_000
    return DEFAULT_BACKTEST_RESULTS_DIR / (
        f"{archive_path.stem}-{safe_name}-{timestamp}-{suffix:09d}"
    )
