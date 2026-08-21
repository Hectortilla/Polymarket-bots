"""Shared PostgreSQL identifiers and constraints for run rows."""

from enum import StrEnum

from sqlalchemy import Enum

from polybot_control_plane.runs.status import RunStatus


RUNS_TABLE_NAME = "runs"
DEFINITION_VERSION_CHECK = "definition_version > 0"
DEFINITION_VERSION_CONSTRAINT_NAME = "ck_runs_definition_version_positive"
RUN_STATUS_CONSTRAINT_NAME = "run_status"


class RunColumn(StrEnum):
    ID = "id"
    DEFINITION_ID = "definition_id"
    DEFINITION_VERSION = "definition_version"
    CONFIG = "config"
    STATUS = "status"
    CREATED_AT = "created_at"
    STARTED_AT = "started_at"
    ENDED_AT = "ended_at"
    HEARTBEAT_AT = "heartbeat_at"
    FAILURE_DETAIL = "failure_detail"


def run_status_column_type() -> Enum:
    # Persist public lowercase states and enforce them portably with a CHECK.
    return Enum(
        RunStatus,
        name=RUN_STATUS_CONSTRAINT_NAME,
        values_callable=lambda statuses: [status.value for status in statuses],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
    )
