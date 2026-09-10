"""Shared PostgreSQL identifiers and constraints for run rows."""

from enum import StrEnum

from sqlalchemy import Enum

from api.lifecycle.schema import HISTORY_EXPIRED_AT_COLUMN
from api.runs.status import RunStatus

RUNS_TABLE_NAME = "runs"
RUN_LAUNCH_KEY_CONSTRAINT_NAME = "uq_runs_bot_launch_key"
RUN_STATUS_CONSTRAINT_NAME = "run_status"
RUN_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME = "fk_runs_bot_graph_revision"


class RunColumn(StrEnum):
    ID = "id"
    BOT_ID = "bot_id"
    DEFINITION_ID = "definition_id"
    CONFIG = "config"
    BOT_GRAPH_REVISION_ID = "bot_graph_revision_id"
    STATUS = "status"
    CREATED_AT = "created_at"
    STARTED_AT = "started_at"
    ENDED_AT = "ended_at"
    HEARTBEAT_AT = "heartbeat_at"
    FAILURE_DETAIL = "failure_detail"
    LAUNCH_KEY = "launch_key"
    EXECUTION_TOKEN = "execution_token"
    DELIVERY_ATTEMPTED_AT = "delivery_attempted_at"


INTERNAL_RUN_COLUMNS = frozenset(
    {
        RunColumn.LAUNCH_KEY,
        RunColumn.EXECUTION_TOKEN,
        RunColumn.DELIVERY_ATTEMPTED_AT,
        HISTORY_EXPIRED_AT_COLUMN,
    }
)


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
