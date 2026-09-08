"""SSE framing for durable and live run events."""

from collections.abc import Iterator

from api.events.contracts import LiveRunEvent, PersistedDurableEvent, RunLifecycleEvent
from api.events.ids import require_persisted_event_id

SSE_IDLE_COMMENT = ": keep-alive\n\n"
SSE_ID_FIELD = "id"
SSE_DATA_FIELD = "data"
SSE_FIELD_SEPARATOR = ": "
SSE_FRAME_TERMINATOR = "\n\n"


def event_frames(
    events: tuple[PersistedDurableEvent, ...],
) -> Iterator[tuple[str, int, bool]]:
    for event in events:
        event_id = require_persisted_event_id(event.id)
        terminal = isinstance(event, RunLifecycleEvent) and event.is_terminal()
        yield sse_frame(event), event_id, terminal


def sse_frame(event: PersistedDurableEvent | LiveRunEvent) -> str:
    persisted_id = getattr(event, "id", None)
    event_id = (
        ""
        if persisted_id is None
        else f"{SSE_ID_FIELD}{SSE_FIELD_SEPARATOR}{persisted_id}\n"
    )
    return (
        f"{event_id}{SSE_DATA_FIELD}{SSE_FIELD_SEPARATOR}{event.model_dump_json()}"
        f"{SSE_FRAME_TERMINATOR}"
    )
