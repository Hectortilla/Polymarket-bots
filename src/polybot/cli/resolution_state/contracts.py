"""Typed durable records for resolution settlement state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from polybot.framework.events.resolution_fields import (
    RESOLUTION_RESOLVED_AT_MS_FIELD,
    RESOLUTION_SETTLED_AT_MS_FIELD,
    RESOLUTION_SOURCE_FIELD,
    RESOLUTION_WINNING_OUTCOME_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
)

from .schema import RESOLUTION_RECORD_FIELDS


@dataclass(frozen=True, slots=True)
class ResolutionRecord:
    winning_token_id: str
    winning_outcome: str
    resolved_at_ms: int
    settled_at_ms: int
    source: str

    @classmethod
    def from_dict(cls, value: object) -> ResolutionRecord:
        if not isinstance(value, dict):
            raise ValueError("resolution ledger record must be an object")
        if frozenset(value) != RESOLUTION_RECORD_FIELDS:
            raise ValueError("resolution ledger record fields are malformed")
        winning_token_id = value.get(RESOLUTION_WINNING_TOKEN_ID_FIELD)
        winning_outcome = value.get(RESOLUTION_WINNING_OUTCOME_FIELD)
        source = value.get(RESOLUTION_SOURCE_FIELD)
        if (
            not isinstance(winning_token_id, str)
            or not winning_token_id
            or not isinstance(winning_outcome, str)
            or not winning_outcome.strip()
            or not isinstance(source, str)
            or not source
        ):
            raise ValueError("resolution ledger record identity is invalid")
        timestamps: dict[str, int] = {}
        for key in (
            RESOLUTION_RESOLVED_AT_MS_FIELD,
            RESOLUTION_SETTLED_AT_MS_FIELD,
        ):
            timestamp = value.get(key)
            if (
                not isinstance(timestamp, int)
                or isinstance(timestamp, bool)
                or timestamp < 0
            ):
                raise ValueError(f"resolution ledger {key} is invalid")
            timestamps[key] = timestamp
        return cls(
            winning_token_id=winning_token_id,
            winning_outcome=winning_outcome.strip(),
            resolved_at_ms=timestamps[RESOLUTION_RESOLVED_AT_MS_FIELD],
            settled_at_ms=timestamps[RESOLUTION_SETTLED_AT_MS_FIELD],
            source=source,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            RESOLUTION_WINNING_TOKEN_ID_FIELD: self.winning_token_id,
            RESOLUTION_WINNING_OUTCOME_FIELD: self.winning_outcome,
            RESOLUTION_RESOLVED_AT_MS_FIELD: self.resolved_at_ms,
            RESOLUTION_SETTLED_AT_MS_FIELD: self.settled_at_ms,
            RESOLUTION_SOURCE_FIELD: self.source,
        }


ResolutionRecords: TypeAlias = dict[str, ResolutionRecord]
