"""Small health-metric calculations used by the dashboard projection."""

from __future__ import annotations

from collections import deque


def average(values: deque[int]) -> int | None:
    return None if not values else round(sum(values) / len(values))


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
