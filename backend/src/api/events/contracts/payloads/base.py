from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MAX_JSON_INTEGER = 2**53 - 1
type NonNegativeJsonInteger = Annotated[int, Field(ge=0, le=MAX_JSON_INTEGER)]


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


BROKER_FILL_STATUS_PATH = ("fill", "status")
ACTIVITY_SEVERITY_FIELD = "severity"
SETTLEMENT_PAPER_POSITIONS_PATH = ("settlement", "paper_positions")
