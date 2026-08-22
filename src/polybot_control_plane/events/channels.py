"""Redis channel contract shared by run-event publishers and subscribers."""

import re
from uuid import UUID

from polybot_control_plane.events.ids import (
    MAX_DURABLE_EVENT_ID_DIGITS,
    is_durable_event_id,
)


RUN_EVENT_CHANNEL_PREFIX = "run:"
_DURABLE_WAKE_PATTERN = re.compile(rb"[0-9]+")


def run_event_channel(run_id: UUID) -> str:
    return f"{RUN_EVENT_CHANNEL_PREFIX}{run_id}"


def encode_durable_wake_frame(event_id: int) -> str:
    if not is_durable_event_id(event_id):
        raise ValueError("durable event ID is outside the PostgreSQL bigint range")
    return str(event_id)


def decode_durable_wake_frame(frame: object) -> int | None:
    if isinstance(frame, str):
        try:
            encoded = frame.encode("ascii")
        except UnicodeEncodeError:
            return None
    elif isinstance(frame, bytes):
        encoded = frame
    else:
        return None
    if _DURABLE_WAKE_PATTERN.fullmatch(encoded) is None:
        return None
    if len(encoded) > MAX_DURABLE_EVENT_ID_DIGITS:
        return None
    event_id = int(encoded)
    if not is_durable_event_id(event_id):
        return None
    return event_id
