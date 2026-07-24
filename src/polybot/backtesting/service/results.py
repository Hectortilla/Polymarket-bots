"""Deterministic identifiers and paths for backtest artifacts."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path


def derived_seed(seed: int, purpose: str) -> int:
    """Derive an independent deterministic random stream from one run seed."""
    digest = hashlib.sha256(f"{seed}:{purpose}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def archive_sha256(path: Path) -> str:
    """Return the immutable source archive fingerprint stored in results."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


DEFAULT_BACKTEST_RESULTS_DIR = Path("backtest-results")


def default_results_dir(archive_path: Path, bot_name: str) -> Path:
    """Build a collision-resistant, readable default artifact directory."""
    safe_name = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in bot_name
    ).strip("-") or "bot"
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    suffix = time.time_ns() % 1_000_000_000
    return DEFAULT_BACKTEST_RESULTS_DIR / (
        f"{archive_path.stem}-{safe_name}-{timestamp}-{suffix:09d}"
    )
