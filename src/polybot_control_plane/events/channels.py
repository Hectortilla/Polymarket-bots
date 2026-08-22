"""Redis channel contract shared by run-event publishers and subscribers."""

from uuid import UUID


RUN_EVENT_CHANNEL_PREFIX = "run:"


def run_event_channel(run_id: UUID) -> str:
    return f"{RUN_EVENT_CHANNEL_PREFIX}{run_id}"
