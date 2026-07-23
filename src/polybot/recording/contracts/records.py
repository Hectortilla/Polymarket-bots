"""Persisted recording rows and their cross-payload invariants."""

from __future__ import annotations

from dataclasses import dataclass

from .anomalies import CaptureAnomalyPayload
from .book import BookBaselinePayload
from .gaps import CoverageGapPayload
from .market import MarketIdentity
from .payloads import (
    RECORDED_PAYLOAD_TYPES,
    RecordedPayload,
    validate_event_identity,
    validate_token_identity,
)
from .validation import validate_nonnegative_int, validate_positive_int


@dataclass(frozen=True, slots=True)
class CaptureAnomalyRecord:
    anomaly_id: int
    session_id: int
    subscription_generation: int
    observed_at_ms: int
    identity: MarketIdentity
    anomaly: CaptureAnomalyPayload

    def __post_init__(self) -> None:
        validate_positive_int(self.anomaly_id, "capture anomaly ID")
        validate_positive_int(self.session_id, "capture anomaly session ID")
        validate_nonnegative_int(
            self.subscription_generation,
            "capture anomaly subscription generation",
        )
        validate_nonnegative_int(
            self.observed_at_ms,
            "capture anomaly observation timestamp",
        )
        if not isinstance(self.identity, MarketIdentity):
            raise ValueError("capture anomaly identity is invalid")
        if not isinstance(self.anomaly, CaptureAnomalyPayload):
            raise ValueError("capture anomaly payload is invalid")


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    sequence: int
    session_id: int
    subscription_generation: int
    observed_at_ms: int
    source_timestamp_ms: int | None
    identity: MarketIdentity | None
    payload: RecordedPayload

    def __post_init__(self) -> None:
        validate_positive_int(self.sequence, "recording event sequence")
        validate_positive_int(self.session_id, "recording session ID")
        validate_nonnegative_int(
            self.subscription_generation,
            "subscription generation",
        )
        validate_nonnegative_int(self.observed_at_ms, "event observation timestamp")
        if self.source_timestamp_ms is not None:
            validate_nonnegative_int(
                self.source_timestamp_ms,
                "event source timestamp",
            )
        if not isinstance(self.payload, RECORDED_PAYLOAD_TYPES):
            raise ValueError("recording event payload type is unsupported")
        validate_event_identity(self.identity, self.payload)


@dataclass(frozen=True, slots=True)
class BookCheckpoint:
    sequence: int
    session_id: int
    subscription_generation: int
    observed_at_ms: int
    identity: MarketIdentity
    book: BookBaselinePayload

    def __post_init__(self) -> None:
        validate_positive_int(self.sequence, "checkpoint sequence")
        validate_positive_int(self.session_id, "checkpoint session ID")
        validate_nonnegative_int(
            self.subscription_generation,
            "checkpoint subscription generation",
        )
        validate_nonnegative_int(
            self.observed_at_ms,
            "checkpoint observation timestamp",
        )
        if not isinstance(self.identity, MarketIdentity):
            raise ValueError("checkpoint market identity is invalid")
        if not isinstance(self.book, BookBaselinePayload):
            raise ValueError("checkpoint book payload is invalid")
        validate_token_identity(self.identity, self.book.token_id, "checkpoint")


@dataclass(frozen=True, slots=True)
class CoverageGapRecord:
    gap_id: int
    event_sequence: int
    session_id: int
    subscription_generation: int
    observed_at_ms: int
    identity: MarketIdentity | None
    gap: CoverageGapPayload

    def __post_init__(self) -> None:
        validate_positive_int(self.gap_id, "coverage gap ID")
        validate_positive_int(self.event_sequence, "coverage gap event sequence")
        validate_positive_int(self.session_id, "coverage gap session ID")
        validate_nonnegative_int(
            self.subscription_generation,
            "coverage gap subscription generation",
        )
        validate_nonnegative_int(self.observed_at_ms, "coverage gap observation")
        if self.identity is not None and not isinstance(self.identity, MarketIdentity):
            raise ValueError("coverage gap identity is invalid")
        if not isinstance(self.gap, CoverageGapPayload):
            raise ValueError("coverage gap payload is invalid")

    @property
    def is_open(self) -> bool:
        return self.gap.ended_at_ms is None
