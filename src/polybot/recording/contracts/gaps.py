"""Coverage-gap contracts for incomplete recording intervals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .validation import (
    normalize_optional_text_fields,
    normalize_text_tuple,
    validate_nonnegative_int,
)


class CoverageGapReason(StrEnum):
    CAPTURE_ENDED = "capture_ended"
    CAPTURE_FAILURE = "capture_failure"
    CURRENT_SLUG_UNAVAILABLE = "current_slug_unavailable"
    DISCONNECT = "disconnect"
    RECORDER_OFFLINE = "recorder_offline"
    RECORDING_WRITE_FAILURE = "recording_write_failure"
    SDK_HANDLE_DROP = "sdk_handle_drop"
    SDK_QUEUE_DROP = "sdk_queue_drop"


@dataclass(frozen=True, slots=True)
class CoverageGapPayload:
    reason: CoverageGapReason
    started_at_ms: int
    ended_at_ms: int | None
    affected_condition_ids: tuple[str, ...] = ()
    affected_market_slugs: tuple[str, ...] = ()
    affected_token_ids: tuple[str, ...] = ()
    details: str | None = None

    def __post_init__(self) -> None:
        try:
            normalized_reason = CoverageGapReason(self.reason)
        except (TypeError, ValueError) as error:
            raise ValueError("coverage gap reason is invalid") from error
        object.__setattr__(self, "reason", normalized_reason)
        normalize_optional_text_fields(self, ("details",))
        validate_nonnegative_int(self.started_at_ms, "coverage gap start")
        if self.ended_at_ms is not None:
            validate_nonnegative_int(self.ended_at_ms, "coverage gap end")
            if self.ended_at_ms < self.started_at_ms:
                raise ValueError("coverage gap cannot end before it starts")
        for name in (
            "affected_condition_ids",
            "affected_market_slugs",
            "affected_token_ids",
        ):
            normalized = normalize_text_tuple(getattr(self, name), name)
            object.__setattr__(self, name, normalized)
