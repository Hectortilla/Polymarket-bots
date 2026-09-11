from pydantic import BaseModel, ConfigDict


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


BROKER_FILL_STATUS_PATH = ("fill", "status")
ACTIVITY_SEVERITY_FIELD = "severity"
SETTLEMENT_PAPER_POSITIONS_PATH = ("settlement", "paper_positions")
