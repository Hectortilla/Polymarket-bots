"""Durable recording-session states and their persistence representation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SessionIntegrityStatus(StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


def session_status_sql_literals() -> str:
    """Return the session states accepted by the archive schema."""
    return ", ".join(f"'{status.value}'" for status in SessionIntegrityStatus)


@dataclass(frozen=True, slots=True)
class SessionState:
    """Validated terminal or active state persisted for one recording session."""

    ended_at_ms: int | None
    clean_close: bool
    integrity_status: SessionIntegrityStatus
    failure_reason: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.integrity_status, SessionIntegrityStatus):
            raise ValueError("recording session integrity status is invalid")
        if self.ended_at_ms is not None and self.ended_at_ms < 0:
            raise ValueError("recording session end must be nonnegative")
        if not isinstance(self.clean_close, bool):
            raise ValueError("recording session clean-close state is invalid")
        if self.failure_reason is not None and (
            not isinstance(self.failure_reason, str) or not self.failure_reason.strip()
        ):
            raise ValueError("recording session failure reason is invalid")
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

    @classmethod
    def active(cls) -> SessionState:
        return cls(None, False, SessionIntegrityStatus.ACTIVE, None)

    @classmethod
    def cleanly_closed(
        cls, *, ended_at_ms: int, has_coverage_gap: bool
    ) -> SessionState:
        status = (
            SessionIntegrityStatus.INCOMPLETE
            if has_coverage_gap
            else SessionIntegrityStatus.COMPLETE
        )
        return cls(ended_at_ms, True, status, None)

    @classmethod
    def failed(cls, *, ended_at_ms: int, failure_reason: str) -> SessionState:
        return cls(
            ended_at_ms,
            False,
            SessionIntegrityStatus.FAILED,
            failure_reason,
        )

    @classmethod
    def interrupted(cls, *, ended_at_ms: int, failure_reason: str) -> SessionState:
        return cls(
            ended_at_ms,
            False,
            SessionIntegrityStatus.INCOMPLETE,
            failure_reason,
        )

    def database_values(self) -> tuple[int | None, int, str, str | None]:
        """Return the values in the archive sessions-update column order."""
        return (
            self.ended_at_ms,
            int(self.clean_close),
            self.integrity_status.value,
            self.failure_reason,
        )
