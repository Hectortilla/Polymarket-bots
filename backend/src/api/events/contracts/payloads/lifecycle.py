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
    Field,
    NonNegativeInt,
    model_validator,
)

from api.events.contracts.payloads.base import EventPayload
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
    queue_depth: NonNegativeInt
    peak_queue_depth: NonNegativeInt
    book_dispatch_lag_ms: NonNegativeInt | None
    book_stale: bool
    book_received_count: NonNegativeInt
    book_coalesced_count: NonNegativeInt

    @classmethod
    def from_observation(cls, event: StreamHealth) -> "StreamHealthPayload":
        return cls.model_validate(event, from_attributes=True)


class RunFailurePayload(EventPayload):
    error: str = Field(min_length=1)
