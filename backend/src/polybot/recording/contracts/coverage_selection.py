"""Validation shared by replay selections and their performance provenance."""

from polybot.integers import validate_nonnegative_int, validate_positive_int


def normalize_coverage_gap_selection(
    gap_ids: tuple[int, ...],
    duration_ms: int,
    open_count: int,
) -> tuple[int, ...]:
    if not isinstance(gap_ids, tuple):
        raise ValueError("coverage gap IDs must be a tuple")
    for gap_id in gap_ids:
        validate_positive_int(gap_id, "coverage gap ID")
    normalized_ids = tuple(sorted(set(gap_ids)))
    validate_nonnegative_int(duration_ms, "coverage gap duration")
    validate_nonnegative_int(open_count, "coverage gap open count")
    if open_count > len(normalized_ids):
        raise ValueError("coverage gap open count exceeds selected gaps")
    return normalized_ids
