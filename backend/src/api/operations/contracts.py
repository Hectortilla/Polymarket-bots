"""Discoverable, payload-free maintenance command response shapes."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field

from api.operations.observations.contracts import AlertCode
from api.operations.schema import OperatorAction, OperatorOutcome
from api.runs.status import RunStatus


class OperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: OperatorAction
    target: UUID | None
    outcome: OperatorOutcome


class OperationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    alerts: tuple[AlertCode, ...]

    @computed_field
    @property
    def healthy(self) -> bool:
        return not self.alerts


class RunInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    owner_user_id: UUID
    status: RunStatus
    created_at: datetime
    heartbeat_at: datetime | None
    ended_at: datetime | None
    event_count: int


class RunInspectionList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    runs: tuple[RunInspection, ...]
