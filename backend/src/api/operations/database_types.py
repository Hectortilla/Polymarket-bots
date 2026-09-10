"""Enum column types shared by migrations and operational persistence."""

from sqlalchemy import Enum

from api.operations.schema import (
    AUDIT_ACTION_CONSTRAINT,
    AUDIT_OUTCOME_CONSTRAINT,
    OperatorAction,
    OperatorOutcome,
)

AUDIT_ACTION_TYPE = Enum(
    OperatorAction,
    values_callable=lambda members: [member.value for member in members],
    name=AUDIT_ACTION_CONSTRAINT,
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
)
AUDIT_OUTCOME_TYPE = Enum(
    OperatorOutcome,
    values_callable=lambda members: [member.value for member in members],
    name=AUDIT_OUTCOME_CONSTRAINT,
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
)
