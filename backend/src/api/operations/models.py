"""Required incident singleton and a payload-free operator audit journal."""

from datetime import datetime
from uuid import UUID, uuid4

from polybot.framework.clock import system_now_utc
from sqlalchemy import Boolean, Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from api.operations.database_types import AUDIT_ACTION_TYPE, AUDIT_OUTCOME_TYPE
from api.operations.schema import (
    AUDIT_TABLE,
    AUDIT_TIME_INDEX,
    CONTROL_TABLE,
    DEFAULT_ADMISSIONS_PAUSED,
    GLOBAL_OPERATION_CONTROL_ROW_ID,
    OperationControlColumn,
    OperatorAction,
    OperatorAuditColumn,
    OperatorOutcome,
)


class OperationControlRow(SQLModel, table=True):
    __tablename__ = CONTROL_TABLE
    id: int = Field(
        default=GLOBAL_OPERATION_CONTROL_ROW_ID,
        primary_key=True,
        sa_column_kwargs={"name": OperationControlColumn.ID},
    )
    admissions_paused: bool = Field(
        default=DEFAULT_ADMISSIONS_PAUSED,
        sa_column=Column(
            OperationControlColumn.ADMISSIONS_PAUSED, Boolean, nullable=False
        ),
    )


class OperatorAuditRow(SQLModel, table=True):
    __tablename__ = AUDIT_TABLE
    __table_args__ = (Index(AUDIT_TIME_INDEX, OperatorAuditColumn.OCCURRED_AT),)
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column_kwargs={"name": OperatorAuditColumn.ID},
    )
    actor: str = Field(
        sa_column=Column(OperatorAuditColumn.ACTOR, String, nullable=False)
    )
    action: OperatorAction = Field(
        sa_column=Column(OperatorAuditColumn.ACTION, AUDIT_ACTION_TYPE, nullable=False)
    )
    target: UUID | None = Field(
        default=None,
        sa_column=Column(OperatorAuditColumn.TARGET, PostgreSQLUUID(as_uuid=True)),
    )
    outcome: OperatorOutcome = Field(
        sa_column=Column(
            OperatorAuditColumn.OUTCOME, AUDIT_OUTCOME_TYPE, nullable=False
        )
    )
    occurred_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(
            OperatorAuditColumn.OCCURRED_AT, DateTime(timezone=True), nullable=False
        ),
    )
