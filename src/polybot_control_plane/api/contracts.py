"""Typed contracts owned by the control-plane HTTP boundary."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from polybot_control_plane.events.contracts import (
    DurableEventId,
    PersistedDurableEvent,
)
from polybot_control_plane.events.ids import (
    FIRST_EVENT_CURSOR,
    MAX_DURABLE_EVENT_ID,
)
from polybot_control_plane.events.pagination import (
    MAX_EVENT_PAGE_LIMIT,
    MIN_EVENT_PAGE_LIMIT,
)


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


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
