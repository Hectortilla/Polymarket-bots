"""Conservative shard-local Redis clock samples; never extrapolate indefinitely."""

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil, floor
from time import monotonic

from redis.asyncio import Redis

from .policy import (
    LIVE_CLOCK_DRIFT_SECONDS,
    LIVE_CLOCK_MAX_AGE_SECONDS,
    LIVE_CLOCK_MAX_ROUNDTRIP_SECONDS,
)

MICROSECONDS_PER_SECOND = 1_000_000


class ClockUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ClockSample:
    redis_us: int
    started: float
    completed: float

    def upper_at(self, now: float) -> int:
        return self.redis_us + ceil(
            (now - self.started + LIVE_CLOCK_DRIFT_SECONDS) * MICROSECONDS_PER_SECOND
        )

    def deadline(self, lifetime: float) -> int:
        # TIME may have executed anywhere in the round trip. Subtract all of it,
        # plus the drift budget, so authority starts no later than sampling start.
        return self.redis_us + floor(
            (lifetime - (self.completed - self.started) - LIVE_CLOCK_DRIFT_SECONDS)
            * MICROSECONDS_PER_SECOND
        )


class ShardClock:
    def __init__(self, *, now: Callable[[], float] = monotonic) -> None:
        self._now = now
        self._sample: ClockSample | None = None
        self.epoch = 0

    def invalidate(self) -> None:
        self._sample = None
        self.epoch += 1

    async def sample(self, redis: Redis) -> ClockSample:
        started = self._now()
        epoch = self.epoch
        try:
            seconds, microseconds = await redis.time()
            if self.epoch != epoch:
                raise ClockUnavailable("Redis clock invalidated during sampling")
            current = ClockSample(
                int(seconds) * MICROSECONDS_PER_SECOND + int(microseconds),
                started,
                self._now(),
            )
            if current.completed - started > LIVE_CLOCK_MAX_ROUNDTRIP_SECONDS:
                raise ClockUnavailable("Redis clock round trip exceeded its bound")
            previous = self._sample
            if previous is not None:
                lower = previous.redis_us + floor(
                    (started - previous.completed - LIVE_CLOCK_DRIFT_SECONDS)
                    * MICROSECONDS_PER_SECOND
                )
                upper = previous.upper_at(current.completed)
                if not lower <= current.redis_us <= upper:
                    raise ClockUnavailable("Redis clock discontinuity")
        except BaseException:
            self.invalidate()
            raise
        self._sample = current
        return current

    def fresh(self, deadline_us: int) -> bool:
        sample = self._sample
        now = self._now()
        return (
            sample is not None
            and now - sample.started <= LIVE_CLOCK_MAX_AGE_SECONDS
            and sample.upper_at(now) < deadline_us
        )
