"""Durable run-event replay and SSE endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import StreamingResponse

from polybot_control_plane.api.contracts import (
    EventCursorValue,
    EventPageLimitValue,
    RunEventPage,
)
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
from polybot_control_plane.api.responses import NOT_FOUND_RESPONSE
from polybot_control_plane.api.sse import RunEventStreamer
from polybot_control_plane.events.contracts import (
    LIVE_EVENT_MODELS,
    PERSISTED_DURABLE_EVENT_ADAPTER,
    LiveRunEvent,
    PersistedDurableEvent,
)
from polybot_control_plane.events.ids import FIRST_EVENT_CURSOR
from polybot_control_plane.events.pagination import DEFAULT_EVENT_PAGE_LIMIT
from polybot_control_plane.events.store import EventStore


SSE_MEDIA_TYPE = "text/event-stream"
LAST_EVENT_ID_HEADER = "Last-Event-ID"
DURABLE_EVENT_SCHEMA_REFERENCE = "#/components/schemas/PersistedDurableEvent"
LIVE_EVENT_SCHEMA_REFERENCES = tuple(
    f"#/components/schemas/{model.__name__}"
    for model in LIVE_EVENT_MODELS
)

router = APIRouter()


@router.get(
    RUN_EVENTS_PATH,
    response_model=RunEventPage,
    operation_id=READ_RUN_EVENTS_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def read_run_events(
    run_id: UUID,
    session_factory: SessionFactoryDependency,
    before_event_id: EventCursorValue | None = None,
    limit: EventPageLimitValue = DEFAULT_EVENT_PAGE_LIMIT,
) -> RunEventPage:
    async with session_factory() as session:
        await require_stored_run(session, run_id)
        page = await EventStore(session).read_page(
            run_id,
            before_event_id=before_event_id,
            limit=limit,
        )
    return RunEventPage(
        events=tuple(
            PERSISTED_DURABLE_EVENT_ADAPTER.validate_python(
                event.model_dump()
            )
            for event in page.events
        ),
        next_before_event_id=page.next_before_event_id,
    )


@router.get(
    RUN_EVENTS_STREAM_PATH,
    response_class=StreamingResponse,
    response_model=PersistedDurableEvent | LiveRunEvent,
    operation_id=STREAM_RUN_EVENTS_OPERATION_ID,
    responses={
        **NOT_FOUND_RESPONSE,
        status.HTTP_200_OK: {
            "content": {
                SSE_MEDIA_TYPE: {
                    "schema": {
                        "oneOf": [
                            {"$ref": DURABLE_EVENT_SCHEMA_REFERENCE},
                            *(
                                {"$ref": reference}
                                for reference in LIVE_EVENT_SCHEMA_REFERENCES
                            ),
                        ]
                    }
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
    after_event_id: Annotated[EventCursorValue, Query()] = FIRST_EVENT_CURSOR,
    last_event_id: Annotated[
        EventCursorValue | None,
        Header(alias=LAST_EVENT_ID_HEADER),
    ] = None,
) -> StreamingResponse:
    async with session_factory() as session:
        await require_stored_run(session, run_id)
    cursor = last_event_id if last_event_id is not None else after_event_id
    streamer = RunEventStreamer(run_id, request, session_factory, redis)
    return StreamingResponse(
        streamer.stream(cursor),
        media_type=SSE_MEDIA_TYPE,
    )
