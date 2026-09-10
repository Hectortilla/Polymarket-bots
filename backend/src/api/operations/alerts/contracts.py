"""Pure operational alert detection contract."""

from dataclasses import dataclass
from enum import StrEnum

from api.operations.observations.contracts import AlertCode


class ThresholdDirection(StrEnum):
    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class AlertDefinition:
    code: AlertCode
    threshold: float
    unit: str
    direction: ThresholdDirection
    response: str

    def breached(self, measurement: float) -> bool:
        if self.direction is ThresholdDirection.AT_LEAST:
            return measurement >= self.threshold
        if self.direction is ThresholdDirection.AT_MOST:
            return measurement <= self.threshold
        raise ValueError("unavailable alerts require an unavailable probe result")
