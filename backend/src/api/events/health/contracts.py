"""Stored health envelopes and normalized observations suitable for alert decisions."""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, NonNegativeInt

from api.events.contracts.payloads.lifecycle import StreamHealthPayload
from api.events.health.policy import FEED_TTL_SECONDS


class AvailableFeedHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    book_stale: bool
    book_dispatch_lag_ms: NonNegativeInt


class FeedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_at: AwareDatetime
    health: StreamHealthPayload

    def available_health(self, now: datetime) -> AvailableFeedHealth | None:
        age_seconds = (now - self.observed_at).total_seconds()
        if (
            not 0 <= age_seconds <= FEED_TTL_SECONDS
            or self.health.book_dispatch_lag_ms is None
        ):
            return None
        return AvailableFeedHealth(
            book_stale=self.health.book_stale,
            book_dispatch_lag_ms=self.health.book_dispatch_lag_ms,
        )
