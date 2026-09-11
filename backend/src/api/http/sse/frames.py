"""SSE framing for durable and live run events."""

from collections.abc import Iterator

from api.events.contracts import LiveRunEvent, PersistedDurableEvent, RunLifecycleEvent
from api.events.delivery import EventDelivery
from api.events.ids import require_persisted_event_id
from api.events.views import DASHBOARD_SSE_EVENT

SSE_IDLE_COMMENT = ": keep-alive\n\n"
SSE_ID_FIELD = "id"
SSE_DATA_FIELD = "data"
SSE_FIELD_SEPARATOR = ": "
SSE_FRAME_TERMINATOR = "\n\n"


def event_frames(
    events: tuple[EventDelivery, ...],
) -> Iterator[tuple[str, int, bool]]:
    for delivery in events:
        event = delivery.event
        event_id = require_persisted_event_id(event.id)
        terminal = isinstance(event, RunLifecycleEvent) and event.is_terminal()
        yield (
            sse_frame(event, dashboard_only=delivery.dashboard_only),
            event_id,
            terminal,
        )


def sse_frame(
    event: PersistedDurableEvent | LiveRunEvent, *, dashboard_only: bool = False
) -> str:
    persisted_id = getattr(event, "id", None)
    event_id = (
        ""
        if persisted_id is None
        else f"{SSE_ID_FIELD}{SSE_FIELD_SEPARATOR}{persisted_id}\n"
    )
    channel = f"event: {DASHBOARD_SSE_EVENT}\n" if dashboard_only else ""
    return (
        f"{event_id}{channel}{SSE_DATA_FIELD}{SSE_FIELD_SEPARATOR}{event.model_dump_json()}"
        f"{SSE_FRAME_TERMINATOR}"
    )
