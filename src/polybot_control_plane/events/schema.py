"""Database identifiers for durable run events."""

from enum import StrEnum

from sqlalchemy import Enum

from .kinds import EVENT_DISCRIMINATOR_FIELD, EventKind


RUN_EVENTS_TABLE_NAME = "run_events"
RUN_EVENTS_RUN_ID_INDEX_NAME = "ix_run_events_run_id"
RUN_EVENTS_CURSOR_INDEX_NAME = "ix_run_events_run_id_id"
EVENT_KIND_CONSTRAINT_NAME = "run_event_kind"


class EventColumn(StrEnum):
    ID = "id"
    RUN_ID = "run_id"
    KIND = EVENT_DISCRIMINATOR_FIELD
    OCCURRED_AT = "occurred_at"
    PAYLOAD = "payload"


def event_kind_column_type() -> Enum:
    return Enum(
        EventKind,
        name=EVENT_KIND_CONSTRAINT_NAME,
        native_enum=False,
        values_callable=lambda kinds: [kind.value for kind in kinds],
        create_constraint=True,
        validate_strings=True,
    )
