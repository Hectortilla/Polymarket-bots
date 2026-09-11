"""Validation and serialization of live event frames."""

from pydantic import ValidationError

from api.events.contracts import LIVE_RUN_EVENT_ADAPTER, LiveRunEvent


def encode_live_event_frame(event: LiveRunEvent) -> str:
    return event.model_dump_json()


def decode_live_event_frame(frame: object) -> LiveRunEvent | None:
    if isinstance(frame, bytes):
        try:
            frame = frame.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(frame, str):
        return None
    try:
        return LIVE_RUN_EVENT_ADAPTER.validate_json(frame)
    except ValidationError:
        return None
