"""Durable run-event replay and SSE endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import StreamingResponse

from polybot_control_plane.api.contracts import EventCursorValue
from polybot_control_plane.api.dependencies import (
    RedisDependency,
    SessionFactoryDependency,
)
from polybot_control_plane.api.routes.paths import (
    READ_RUN_EVENTS_OPERATION_ID,
    RUN_EVENTS_PATH,
    RUN_EVENTS_STREAM_PATH,
    STREAM_RUN_EVENTS_OPERATION_ID,
)
from polybot_control_plane.api.routes.run_lookup import require_stored_run
from polybot_control_plane.api.sse import stream_durable_events
from polybot_control_plane.events.contracts import DurableEvent
from polybot_control_plane.events.ids import FIRST_EVENT_CURSOR
from polybot_control_plane.events.store import EventStore


SSE_MEDIA_TYPE = "text/event-stream"
LAST_EVENT_ID_HEADER = "Last-Event-ID"
DURABLE_EVENT_SCHEMA_REFERENCE = "#/components/schemas/DurableEvent"

type EventCursor = Annotated[EventCursorValue, Query()]

router = APIRouter()


@router.get(
    RUN_EVENTS_PATH,
    response_model=list[DurableEvent],
    operation_id=READ_RUN_EVENTS_OPERATION_ID,
)
async def read_run_events(
    run_id: UUID,
    session_factory: SessionFactoryDependency,
    after_event_id: EventCursor = FIRST_EVENT_CURSOR,
) -> tuple[DurableEvent, ...]:
    async with session_factory() as session:
        await require_stored_run(session, run_id)
        return await EventStore(session).read(
            run_id,
            after_event_id=after_event_id,
        )


@router.get(
    RUN_EVENTS_STREAM_PATH,
    response_class=StreamingResponse,
    operation_id=STREAM_RUN_EVENTS_OPERATION_ID,
    responses={
        status.HTTP_200_OK: {
            "content": {
                SSE_MEDIA_TYPE: {
                    "schema": {"$ref": DURABLE_EVENT_SCHEMA_REFERENCE}
                }
            }
        }
    },
)
async def stream_run_events(
    run_id: UUID,
    request: Request,
    session_factory: SessionFactoryDependency,
    redis: RedisDependency,
    after_event_id: EventCursor = FIRST_EVENT_CURSOR,
    last_event_id: Annotated[
        EventCursorValue | None,
        Header(alias=LAST_EVENT_ID_HEADER),
    ] = None,
) -> StreamingResponse:
    async with session_factory() as session:
        await require_stored_run(session, run_id)
    cursor = last_event_id if last_event_id is not None else after_event_id
    return StreamingResponse(
        stream_durable_events(
            run_id,
            after_event_id=cursor,
            request=request,
            session_factory=session_factory,
            redis=redis,
        ),
        media_type=SSE_MEDIA_TYPE,
    )
