from __future__ import annotations

import pytest

from polybot.framework.markets import FixedBucketTiming


def test_fixed_bucket_timing_uses_the_current_unix_bucket() -> None:
    timing = FixedBucketTiming.at(320_000, bucket_seconds=300)

    assert timing.elapsed_ms == 20_000
    assert timing.remaining_ms == 280_000
    assert timing.bucket_end_ms == 600_000
    assert timing.allows_entry(delay_ms=20_000, cutoff_ms=45_000)


def test_fixed_bucket_timing_closes_the_entry_window_at_the_cutoff() -> None:
    timing = FixedBucketTiming.at(255_000, bucket_seconds=300)

    assert not timing.allows_entry(delay_ms=20_000, cutoff_ms=45_000)


@pytest.mark.parametrize(
    ("now_ms", "bucket_seconds"),
    ((-1, 300), (0, 0)),
)
def test_fixed_bucket_timing_rejects_invalid_inputs(
    now_ms: int,
    bucket_seconds: int,
) -> None:
    with pytest.raises(ValueError):
        FixedBucketTiming.at(now_ms, bucket_seconds)


@pytest.mark.parametrize("bound", (-1,))
def test_fixed_bucket_timing_rejects_invalid_entry_bounds(bound: int) -> None:
    timing = FixedBucketTiming.at(0, bucket_seconds=300)

    with pytest.raises(ValueError):
        timing.allows_entry(delay_ms=bound, cutoff_ms=0)
