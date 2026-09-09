"""Typed contracts owned by the control-plane HTTP boundary."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.events.contracts import (
    DurableEventId,
    PersistedDurableEvent,
)
from api.events.ids import (
    FIRST_EVENT_CURSOR,
    MAX_DURABLE_EVENT_ID,
)
from api.events.pagination import (
    MAX_EVENT_PAGE_LIMIT,
    MIN_EVENT_PAGE_LIMIT,
)
from api.limits.errors import ResourceLimitCode

type EventCursorValue = Annotated[
    int,
    Field(ge=FIRST_EVENT_CURSOR, le=MAX_DURABLE_EVENT_ID),
]

type EventPageLimitValue = Annotated[
    int,
    Field(ge=MIN_EVENT_PAGE_LIMIT, le=MAX_EVENT_PAGE_LIMIT),
]


class RunEventPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: tuple[PersistedDurableEvent, ...]
    next_before_event_id: DurableEventId | None


HEALTH_STATUS_OK = "ok"


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[HEALTH_STATUS_OK] = HEALTH_STATUS_OK


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
    code: ResourceLimitCode | None = None


class RequestValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class RequestValidationFailure(BaseModel):
    detail: list[RequestValidationIssue]
