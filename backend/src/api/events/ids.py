"""Dependency-light durable event ID and cursor contracts."""


FIRST_EVENT_CURSOR = 0
FIRST_DURABLE_EVENT_ID = 1
# Browser consumers compare cursors as JavaScript numbers. Keep the public
# contract within the exact integer range shared by Python and JavaScript.
MAX_DURABLE_EVENT_ID = 2**53 - 1
MAX_DURABLE_EVENT_ID_DIGITS = len(str(MAX_DURABLE_EVENT_ID))


def is_durable_event_id(event_id: int) -> bool:
    return FIRST_DURABLE_EVENT_ID <= event_id <= MAX_DURABLE_EVENT_ID


def require_persisted_event_id(event_id: int | None) -> int:
    if event_id is None:
        raise ValueError("persisted durable event is missing its ID")
    return event_id
