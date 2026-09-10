"""Durable operation identifiers and finite mutation contracts."""

from enum import StrEnum


class OperatorAction(StrEnum):
    SUSPEND = "suspend"
    RESUME_ACCOUNT = "resume-account"
    STOP_ALL = "stop-all"
    RESUME_ADMISSIONS = "resume-admissions"
    STOP_RUN = "stop-run"

    @property
    def requires_target(self) -> bool:
        return self in ACCOUNT_ACTIONS or self is OperatorAction.STOP_RUN


ACCOUNT_ACTIONS = frozenset({OperatorAction.SUSPEND, OperatorAction.RESUME_ACCOUNT})


class OperatorOutcome(StrEnum):
    APPLIED = "applied"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"


class OperationControlColumn(StrEnum):
    ID = "id"
    ADMISSIONS_PAUSED = "admissions_paused"


class OperatorAuditColumn(StrEnum):
    ID = "id"
    ACTOR = "actor"
    ACTION = "action"
    TARGET = "target"
    OUTCOME = "outcome"
    OCCURRED_AT = "occurred_at"


CONTROL_TABLE = "operation_control"
AUDIT_TABLE = "operation_audit"
GLOBAL_OPERATION_CONTROL_ROW_ID = 1
DEFAULT_ADMISSIONS_PAUSED = False
AUDIT_TIME_INDEX = "ix_operation_audit_occurred_at"
AUDIT_ACTION_CONSTRAINT = "ck_operation_audit_action"
AUDIT_OUTCOME_CONSTRAINT = "ck_operation_audit_outcome"
