"""Database identifiers for durable run events."""

from enum import StrEnum

from .contracts import EventKind


RUN_EVENTS_TABLE_NAME = "run_events"
RUN_EVENTS_RUN_ID_INDEX_NAME = "ix_run_events_run_id"


class EventColumn(StrEnum):
    ID = "id"
    RUN_ID = "run_id"
    KIND = "kind"
    OCCURRED_AT = "occurred_at"
    PAYLOAD = "payload"


def event_kind_column_type():
    from sqlalchemy import Enum

    return Enum(
        EventKind,
        native_enum=False,
        values_callable=lambda kinds: [kind.value for kind in kinds],
    )
