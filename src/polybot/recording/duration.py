"""Recorder duration parsing."""

from __future__ import annotations

import re


_DURATION_PATTERN = re.compile(r"^(?P<amount>[1-9][0-9]*)(?P<unit>[smhd])$")
_SECONDS_BY_UNIT = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
}


def parse_duration_seconds(value: str) -> int:
    """Parse a positive recorder duration such as ``30m`` or ``10d``."""
    match = _DURATION_PATTERN.fullmatch(value.strip().lower())
    if match is None:
        raise ValueError(
            "duration must be a positive integer followed by s, m, h, or d"
        )
    amount = int(match.group("amount"))
    return amount * _SECONDS_BY_UNIT[match.group("unit")]
