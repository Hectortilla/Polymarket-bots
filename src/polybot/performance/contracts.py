"""Stable contracts for performance samples and result summaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


RESULT_SCHEMA_VERSION = 1
DEFAULT_REPORT_INTERVAL_MS = 1_000
SUMMARY_FILE_NAME = "summary.json"
EQUITY_FILE_NAME = "equity.csv"
ORDERS_FILE_NAME = "orders.csv"

EQUITY_FIELDS = (
    "timestamp_ms",
    "sample_reason",
    "cash_usdc",
    "marked_position_value_usdc",
    "equity_usdc",
    "pnl_usdc",
    "fees_usdc",
    "exposure_usdc",
    "position_count",
    "valuation_status",
)

ORDER_FIELDS = (
    "submitted_at_ms",
    "completed_at_ms",
    "order_id",
    "market_slug",
    "condition_id",
    "token_id",
    "side",
    "requested_price",
    "requested_size",
    "status",
    "filled_size",
    "average_price",
    "fee_usdc",
    "reject_reason",
    "reject_message",
    "strategy_reason",
    "source_id",
)


class PerformanceRunKind(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"


class PerformanceRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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
        if self.kind is PerformanceRunKind.BACKTEST and (
            not self.archive_sha256
            or self.archive_schema_version is None
            or not self.archive_target_identity
        ):
            raise ValueError("backtest provenance requires archive identity")


@dataclass(frozen=True, slots=True)
class RunSelection:
    session_id: int | None
    start_ms: int
    end_ms: int | None
    market_slugs: tuple[str, ...]
    replay_cutoff_sequence: int | None = None
    session_integrity_status: str | None = None
    uses_partial_session: bool = False

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
        if (
            self.session_integrity_status is not None
            and not self.session_integrity_status.strip()
        ):
            raise ValueError("performance session integrity status must not be empty")
        if not isinstance(self.uses_partial_session, bool):
            raise ValueError("performance partial-session marker must be boolean")


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
