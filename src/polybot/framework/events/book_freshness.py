"""Paired-book freshness policy shared by trading strategies."""

from polybot.framework.timestamps import NONNEGATIVE_TIMESTAMP_FLOOR


def paired_observations_are_current(
    observed_at_ms: tuple[int, ...],
    *,
    now_ms: int,
    maximum_age_ms: int,
    maximum_skew_ms: int,
) -> bool:
    return bool(observed_at_ms) and (
        all(
            NONNEGATIVE_TIMESTAMP_FLOOR
            <= now_ms - timestamp
            <= maximum_age_ms
            for timestamp in observed_at_ms
        )
        and max(observed_at_ms) - min(observed_at_ms) <= maximum_skew_ms
    )
