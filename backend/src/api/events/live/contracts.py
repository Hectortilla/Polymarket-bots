"""Internal publication contracts; execution tokens never leave this boundary."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from api.events.contracts import LiveRunSnapshot


@dataclass(frozen=True, slots=True)
class LivePermit:
    run_id: UUID
    registration: int
    shard_index: int
    local_deadline: float
    redis_deadline_us: int
    clock_epoch: int = 0

    def valid_at(self, now: float, clock_epoch: int) -> bool:
        return now < self.local_deadline and self.clock_epoch == clock_epoch


@dataclass(frozen=True, slots=True)
class RegisteredRun:
    run_id: UUID
    execution_token: UUID
    registration: int
    shard_index: int


# Internal Redis envelope: deadlines use a shard clock, not the browser clock.


class PublishedSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    publication_deadline_us: int = Field(gt=0)
    snapshot: LiveRunSnapshot
