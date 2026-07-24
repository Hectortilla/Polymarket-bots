from __future__ import annotations

from dataclasses import dataclass

def market_bucket_slug(
    prefix: str,
    now_ms: int,
    bucket_seconds: int,
    *,
    bucket_offset: int = 0,
) -> str:
    """Build the canonical slug for a fixed-width Unix-time market bucket."""
    if not prefix.strip():
        raise ValueError("prefix must not be empty")
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    bucket_start = _market_bucket_start(now_ms, bucket_seconds, bucket_offset)
    return f"{prefix}-{bucket_start}"


def _market_bucket_start(now_ms: int, bucket_seconds: int, bucket_offset: int) -> int:
    return (now_ms // 1000 // bucket_seconds + bucket_offset) * bucket_seconds


@dataclass(frozen=True, slots=True)
class FixedBucketTiming:
    """Elapsed and remaining time for one fixed-width Unix-time bucket."""

    elapsed_ms: int
    remaining_ms: int
    bucket_end_ms: int

    @classmethod
    def at(cls, now_ms: int, bucket_seconds: int) -> FixedBucketTiming:
        if now_ms < 0:
            raise ValueError("now_ms must be nonnegative")
        if bucket_seconds <= 0:
            raise ValueError("bucket_seconds must be positive")
        return cls._at_valid_time(now_ms, bucket_seconds)

    @classmethod
    def _at_valid_time(
        cls,
        now_ms: int,
        bucket_seconds: int,
    ) -> FixedBucketTiming:
        bucket_ms = bucket_seconds * 1_000
        elapsed_ms = now_ms % bucket_ms
        return cls(
            elapsed_ms=elapsed_ms,
            remaining_ms=bucket_ms - elapsed_ms,
            bucket_end_ms=now_ms - elapsed_ms + bucket_ms,
        )

    def allows_entry(self, *, delay_ms: int, cutoff_ms: int) -> bool:
        """Whether a strategy's entry window remains open in this bucket."""
        if delay_ms < 0 or cutoff_ms < 0:
            raise ValueError("entry-window bounds must be nonnegative")
        return self._allows_valid_entry(delay_ms, cutoff_ms)

    def _allows_valid_entry(self, delay_ms: int, cutoff_ms: int) -> bool:
        return self.elapsed_ms >= delay_ms and self.remaining_ms > cutoff_ms
