"""Run-time performance reporting contracts and accounting counters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from polybot.backtesting.contracts import BacktestGapPolicy
from polybot.recording.contracts.session import SessionIntegrityStatus


class PerformanceRunKind(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"


class PerformanceRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_partial(self) -> bool:
        """Whether this terminal state represents an incomplete run."""
        return self is not PerformanceRunStatus.COMPLETED

    def validate_error(self, error: str | None) -> None:
        """Enforce the terminal-error contract shared by writers and readers."""
        if self is PerformanceRunStatus.FAILED:
            if not isinstance(error, str) or not error.strip():
                raise ValueError("failed performance runs require an error")
        elif error is not None:
            raise ValueError("non-failed performance runs cannot include an error")


class SampleReason(StrEnum):
    START = "start"
    INTERVAL = "interval"
    FILL = "fill"
    SETTLEMENT = "settlement"
    END = "end"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class RunProvenance:
    kind: PerformanceRunKind
    bot_spec: str
    configuration: object
    seed: int | None = None
    archive_sha256: str | None = None
    archive_schema_version: int | None = None
    archive_target_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PerformanceRunKind):
            raise ValueError("performance run kind is invalid")
        if not self.bot_spec.strip():
            raise ValueError("performance bot spec must not be empty")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ValueError("performance seed must be an integer")
        if self.archive_schema_version is not None and (
            isinstance(self.archive_schema_version, bool)
            or not isinstance(self.archive_schema_version, int)
            or self.archive_schema_version <= 0
        ):
            raise ValueError("archive schema version must be positive")
        for value, name in (
            (self.archive_sha256, "archive checksum"),
            (self.archive_target_identity, "archive target identity"),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(f"{name} must be non-empty text or null")
        if self.kind is PerformanceRunKind.BACKTEST and (
            self.archive_sha256 is None
            or self.archive_schema_version is None
            or self.archive_target_identity is None
        ):
            raise ValueError("backtest provenance requires archive identity")


@dataclass(frozen=True, slots=True)
class RunSelection:
    session_id: int | None
    start_ms: int
    end_ms: int | None
    market_slugs: tuple[str, ...]
    replay_cutoff_sequence: int | None = None
    session_integrity_status: SessionIntegrityStatus | None = None
    uses_partial_session: bool = False
    gap_policy: BacktestGapPolicy | None = None
    coverage_gap_ids: tuple[int, ...] = ()
    coverage_gap_duration_ms: int = 0
    coverage_gap_open_count: int = 0

    def __post_init__(self) -> None:
        if self.session_id is not None and (
            isinstance(self.session_id, bool)
            or not isinstance(self.session_id, int)
            or self.session_id <= 0
        ):
            raise ValueError("performance session ID must be positive")
        if (
            isinstance(self.start_ms, bool)
            or not isinstance(self.start_ms, int)
            or self.start_ms < 0
        ):
            raise ValueError("performance start timestamp must be nonnegative")
        if self.end_ms is not None and (
            isinstance(self.end_ms, bool)
            or not isinstance(self.end_ms, int)
            or self.end_ms < self.start_ms
        ):
            raise ValueError("performance end timestamp must not precede start")
        if any(not slug.strip() for slug in self.market_slugs):
            raise ValueError("performance market slugs must not be empty")
        if len(self.market_slugs) != len(set(self.market_slugs)):
            raise ValueError("performance market slugs must be unique")
        if self.replay_cutoff_sequence is not None and (
            isinstance(self.replay_cutoff_sequence, bool)
            or not isinstance(self.replay_cutoff_sequence, int)
            or self.replay_cutoff_sequence <= 0
        ):
            raise ValueError("performance replay cutoff must be positive")
        if self.session_integrity_status is not None and not isinstance(
            self.session_integrity_status, SessionIntegrityStatus
        ):
            raise ValueError("performance session integrity status is invalid")
        if not isinstance(self.uses_partial_session, bool):
            raise ValueError("performance partial-session marker must be boolean")
        if self.gap_policy is not None:
            try:
                normalized_gap_policy = BacktestGapPolicy(
                    str(self.gap_policy).strip()
                )
            except (TypeError, ValueError) as error:
                raise ValueError("performance gap policy is invalid") from error
            object.__setattr__(self, "gap_policy", normalized_gap_policy)
        if not isinstance(self.coverage_gap_ids, tuple) or any(
            isinstance(gap_id, bool)
            or not isinstance(gap_id, int)
            or gap_id <= 0
            for gap_id in self.coverage_gap_ids
        ):
            raise ValueError("performance coverage gap IDs must be positive integers")
        object.__setattr__(
            self,
            "coverage_gap_ids",
            tuple(sorted(set(self.coverage_gap_ids))),
        )
        for value, name in (
            (self.coverage_gap_duration_ms, "duration"),
            (self.coverage_gap_open_count, "open count"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"performance coverage gap {name} must be nonnegative")
        if self.coverage_gap_open_count > len(self.coverage_gap_ids):
            raise ValueError(
                "performance open coverage gap count exceeds selected gaps"
            )
        if self.gap_policy is None and (
            self.coverage_gap_ids
            or self.coverage_gap_duration_ms
            or self.coverage_gap_open_count
        ):
            raise ValueError("performance coverage gaps require a gap policy")


@dataclass(slots=True)
class PerformanceCounters:
    event_count: int = 0
    dispatch_count: int = 0
    accepted_dispatch_count: int = 0
    skipped_dispatch_count: int = 0
    resolution_count: int = 0

    def record_events(self, count: int = 1) -> None:
        self.event_count += _positive_count(count)

    def record_dispatch(self, accepted: bool | None) -> None:
        if accepted is not None and not isinstance(accepted, bool):
            raise ValueError("performance dispatch outcome must be boolean or null")
        self.dispatch_count += 1
        if accepted is True:
            self.accepted_dispatch_count += 1
        elif accepted is False:
            self.skipped_dispatch_count += 1

    def record_resolutions(self, count: int = 1) -> None:
        self.resolution_count += _positive_count(count)


def _positive_count(count: int) -> int:
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("performance counter increments must be positive")
    return count
