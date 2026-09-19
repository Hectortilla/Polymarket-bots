"""Redis health record contract shared by its read and write adapters."""

from pydantic import BaseModel, ConfigDict, Field

from api.events.contracts.payloads.lifecycle import FeedObservation


class FeedHealthRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: int = Field(gt=0)
    sequence: int = Field(gt=0)
    observed_at_us: int = Field(ge=0)
    observation: FeedObservation
