"""Typed rows and selections returned by recording archives."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import SessionIntegrityStatus


@dataclass(frozen=True, slots=True)
class RecordingSession:
    session_id: int
    started_at_ms: int
    ended_at_ms: int | None
    clean_close: bool
    integrity_status: SessionIntegrityStatus
    recorder_version: str
    sdk_version: str
    failure_reason: str | None

    def __post_init__(self) -> None:
        if self.session_id <= 0 or self.started_at_ms < 0:
            raise ValueError("recording session identity is invalid")
        if self.ended_at_ms is not None and self.ended_at_ms < self.started_at_ms:
            raise ValueError("recording session ends before it starts")
        if not self.recorder_version or not self.sdk_version:
            raise ValueError("recording session version provenance is incomplete")
        if self.integrity_status is SessionIntegrityStatus.ACTIVE:
            valid = (
                self.ended_at_ms is None
                and not self.clean_close
                and self.failure_reason is None
            )
        elif self.integrity_status is SessionIntegrityStatus.COMPLETE:
            valid = (
                self.ended_at_ms is not None
                and self.clean_close
                and self.failure_reason is None
            )
        elif self.integrity_status is SessionIntegrityStatus.FAILED:
            valid = (
                self.ended_at_ms is not None
                and not self.clean_close
                and self.failure_reason is not None
            )
        else:
            valid = self.ended_at_ms is not None and (
                (self.clean_close and self.failure_reason is None)
                or (not self.clean_close and self.failure_reason is not None)
            )
        if not valid:
            raise ValueError("recording session integrity fields are inconsistent")


@dataclass(frozen=True, slots=True)
class RecordingEventBounds:
    """First and last event coordinates for one immutable reader selection."""

    first_sequence: int
    last_sequence: int
    start_at_ms: int
    end_at_ms: int


@dataclass(frozen=True, slots=True)
class RecordingFeatureProvenance:
    feature_name: str
    available_from_session_id: int
    enabled_at_ms: int
    recorder_version: str
