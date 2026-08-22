"""Typed contracts owned by the control-plane HTTP boundary."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from polybot_control_plane.events.ids import (
    FIRST_EVENT_CURSOR,
    MAX_DURABLE_EVENT_ID,
)


type EventCursorValue = Annotated[
    int,
    Field(ge=FIRST_EVENT_CURSOR, le=MAX_DURABLE_EVENT_ID),
]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
