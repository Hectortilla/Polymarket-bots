"""Valuation completeness states shared by artifacts and presentation."""

from collections.abc import Iterable
from enum import StrEnum


class ValuationStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"

    @property
    def is_complete(self) -> bool:
        """Whether the valuation contains no stale or unavailable samples."""
        return self is ValuationStatus.FRESH


def aggregate_valuation_status(
    statuses: Iterable[ValuationStatus],
) -> ValuationStatus:
    observed = set(statuses)
    if ValuationStatus.UNAVAILABLE in observed:
        return ValuationStatus.UNAVAILABLE
    if ValuationStatus.STALE in observed:
        return ValuationStatus.STALE
    return ValuationStatus.FRESH


def history_valuation_status(
    *,
    stale_sample_count: int,
    unavailable_sample_count: int,
) -> ValuationStatus:
    """Derive an equity-history status from its persisted sample counters."""
    statuses = []
    if unavailable_sample_count:
        statuses.append(ValuationStatus.UNAVAILABLE)
    if stale_sample_count:
        statuses.append(ValuationStatus.STALE)
    return aggregate_valuation_status(statuses)
