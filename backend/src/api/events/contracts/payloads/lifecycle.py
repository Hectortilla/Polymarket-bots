from datetime import datetime
from decimal import Decimal
from typing import Literal

from polybot.cli.observability.events import StreamHealth
from polybot.cli.observability.states import (
    BootstrapPhase,
    validate_bootstrap_progress,
)
from polybot.framework.activity import ActivitySeverity, validate_activity_message
from polybot.framework.config.mode import BotMode
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from api.events.contracts.payloads.base import EventPayload, NonNegativeJsonInteger
from api.events.health.policy import FEED_TTL_SECONDS
from api.runs.status import INITIAL_RUN_STATUS, RunStatus


class RunStartedPayload(EventPayload):
    status: Literal[INITIAL_RUN_STATUS] = INITIAL_RUN_STATUS
    name: str = Field(min_length=1)
    mode: BotMode
    initial_cash_usdc: Decimal = Field(gt=0)


class RunStatusPayload(EventPayload):
    status: RunStatus


class RunBootstrapPayload(EventPayload):
    phase: BootstrapPhase
    completed: int
    total: int

    @model_validator(mode="after")
    def _validate_progress(self) -> "RunBootstrapPayload":
        validate_bootstrap_progress(self.completed, self.total)
        return self


class BotActivityPayload(EventPayload):
    message: str
    severity: ActivitySeverity

    @model_validator(mode="after")
    def _validate_message(self) -> "BotActivityPayload":
        validate_activity_message(self.message)
        return self


class StreamHealthPayload(EventPayload):
    queue_depth: NonNegativeJsonInteger
    peak_queue_depth: NonNegativeJsonInteger
    book_dispatch_lag_ms: NonNegativeJsonInteger | None
    book_stale: bool
    book_received_count: NonNegativeJsonInteger
    book_coalesced_count: NonNegativeJsonInteger

    @classmethod
    def from_observation(cls, event: StreamHealth) -> "StreamHealthPayload":
        return cls.model_validate(event, from_attributes=True)


class RunFailurePayload(EventPayload):
    error: str = Field(min_length=1)


class AvailableFeedHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    book_stale: bool
    book_dispatch_lag_ms: NonNegativeJsonInteger


class FeedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_at: AwareDatetime
    health: StreamHealthPayload

    @classmethod
    def from_observation(
        cls, event: StreamHealth, *, observed_at: datetime
    ) -> "FeedObservation":
        return cls(
            observed_at=observed_at, health=StreamHealthPayload.from_observation(event)
        )

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
