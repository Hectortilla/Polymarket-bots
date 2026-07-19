"""Stable contracts for performance samples and result summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from polybot.persistence.json_codec import loads_json
from polybot.recording.contracts import SessionIntegrityStatus


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
    session_integrity_status: SessionIntegrityStatus | None = None
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
        if self.session_integrity_status is not None and not isinstance(
            self.session_integrity_status, SessionIntegrityStatus
        ):
            raise ValueError("performance session integrity status is invalid")
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


@dataclass(frozen=True, slots=True)
class PerformanceMetricsSummary:
    initial_cash_usdc: str
    initial_equity_usdc: str | None
    final_cash_usdc: str
    final_marked_position_value_usdc: str | None
    final_equity_usdc: str | None
    gross_pnl_usdc: str | None
    net_pnl_usdc: str | None
    return_fraction: str | None
    fees_usdc: str
    filled_notional_usdc: str
    max_drawdown_usdc: str | None
    max_drawdown_fraction: str | None
    order_count: int
    fill_count: int
    rejected_order_count: int
    resolution_count: int
    event_count: int
    dispatch_count: int
    accepted_dispatch_count: int
    skipped_dispatch_count: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PerformanceMetricsSummary:
        return cls(
            initial_cash_usdc=_required_string(payload, "initial_cash_usdc"),
            initial_equity_usdc=_optional_string(payload, "initial_equity_usdc"),
            final_cash_usdc=_required_string(payload, "final_cash_usdc"),
            final_marked_position_value_usdc=_optional_string(
                payload, "final_marked_position_value_usdc"
            ),
            final_equity_usdc=_optional_string(payload, "final_equity_usdc"),
            gross_pnl_usdc=_optional_string(payload, "gross_pnl_usdc"),
            net_pnl_usdc=_optional_string(payload, "net_pnl_usdc"),
            return_fraction=_optional_string(payload, "return"),
            fees_usdc=_required_string(payload, "fees_usdc"),
            filled_notional_usdc=_required_string(payload, "filled_notional_usdc"),
            max_drawdown_usdc=_optional_string(payload, "max_drawdown_usdc"),
            max_drawdown_fraction=_optional_string(payload, "max_drawdown_fraction"),
            order_count=_nonnegative_int(payload, "order_count"),
            fill_count=_nonnegative_int(payload, "fill_count"),
            rejected_order_count=_nonnegative_int(payload, "rejected_order_count"),
            resolution_count=_nonnegative_int(payload, "resolution_count"),
            event_count=_nonnegative_int(payload, "event_count"),
            dispatch_count=_nonnegative_int(payload, "dispatch_count"),
            accepted_dispatch_count=_nonnegative_int(
                payload, "accepted_dispatch_count"
            ),
            skipped_dispatch_count=_nonnegative_int(payload, "skipped_dispatch_count"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_cash_usdc": self.initial_cash_usdc,
            "initial_equity_usdc": self.initial_equity_usdc,
            "final_cash_usdc": self.final_cash_usdc,
            "final_marked_position_value_usdc": self.final_marked_position_value_usdc,
            "final_equity_usdc": self.final_equity_usdc,
            "gross_pnl_usdc": self.gross_pnl_usdc,
            "net_pnl_usdc": self.net_pnl_usdc,
            "return": self.return_fraction,
            "fees_usdc": self.fees_usdc,
            "filled_notional_usdc": self.filled_notional_usdc,
            "max_drawdown_usdc": self.max_drawdown_usdc,
            "max_drawdown_fraction": self.max_drawdown_fraction,
            "order_count": self.order_count,
            "fill_count": self.fill_count,
            "rejected_order_count": self.rejected_order_count,
            "resolution_count": self.resolution_count,
            "event_count": self.event_count,
            "dispatch_count": self.dispatch_count,
            "accepted_dispatch_count": self.accepted_dispatch_count,
            "skipped_dispatch_count": self.skipped_dispatch_count,
        }


@dataclass(frozen=True, slots=True)
class PerformanceValuationSummary:
    final_status: str
    history_status: str
    drawdown_status: str
    complete: bool
    estimated: bool
    sample_count: int
    available_sample_count: int
    stale_sample_count: int
    unavailable_sample_count: int

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> PerformanceValuationSummary:
        from polybot.performance.valuation import ValuationStatus

        final_status = ValuationStatus(_required_string(payload, "final_status"))
        history_status = ValuationStatus(_required_string(payload, "history_status"))
        drawdown_status = ValuationStatus(
            _required_string(payload, "drawdown_status")
        )
        complete = _required_bool(payload, "complete")
        estimated = _required_bool(payload, "estimated")
        if complete is not (history_status is ValuationStatus.FRESH):
            raise ValueError(
                "performance summary valuation completeness is inconsistent"
            )
        return cls(
            final_status=final_status.value,
            history_status=history_status.value,
            drawdown_status=drawdown_status.value,
            complete=complete,
            estimated=estimated,
            sample_count=_nonnegative_int(payload, "sample_count"),
            available_sample_count=_nonnegative_int(
                payload, "available_sample_count"
            ),
            stale_sample_count=_nonnegative_int(payload, "stale_sample_count"),
            unavailable_sample_count=_nonnegative_int(
                payload, "unavailable_sample_count"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "final_status": self.final_status,
            "history_status": self.history_status,
            "drawdown_status": self.drawdown_status,
            "complete": self.complete,
            "estimated": self.estimated,
            "sample_count": self.sample_count,
            "available_sample_count": self.available_sample_count,
            "stale_sample_count": self.stale_sample_count,
            "unavailable_sample_count": self.unavailable_sample_count,
        }


@dataclass(frozen=True, slots=True)
class PerformanceSummaryV1:
    status: PerformanceRunStatus
    partial: bool
    error: str | None
    provenance: Mapping[str, object]
    selection: Mapping[str, object]
    timing: Mapping[str, object]
    metrics: PerformanceMetricsSummary
    valuation: PerformanceValuationSummary
    open_positions: tuple[Mapping[str, object], ...]
    artifacts: Mapping[str, object]

    @classmethod
    def read(cls, path: str | Path) -> PerformanceSummaryV1:
        payload = loads_json(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("performance summary must contain a JSON object")
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PerformanceSummaryV1:
        if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported performance summary schema version")
        status = PerformanceRunStatus(_required_string(payload, "status"))
        partial = _required_bool(payload, "partial")
        if partial is not (status is not PerformanceRunStatus.COMPLETED):
            raise ValueError("performance summary partial status is inconsistent")
        raw_error = payload.get("error")
        if raw_error is not None and not isinstance(raw_error, str):
            raise ValueError("performance summary error must be text or null")
        open_positions = payload.get("open_positions")
        if not isinstance(open_positions, list) or not all(
            isinstance(position, dict) for position in open_positions
        ):
            raise ValueError("performance summary open positions are malformed")
        return cls(
            status=status,
            partial=partial,
            error=raw_error,
            provenance=_required_mapping(payload, "provenance"),
            selection=_required_mapping(payload, "selection"),
            timing=_required_mapping(payload, "timing"),
            metrics=PerformanceMetricsSummary.from_dict(
                _required_mapping(payload, "metrics")
            ),
            valuation=PerformanceValuationSummary.from_dict(
                _required_mapping(payload, "valuation")
            ),
            open_positions=tuple(open_positions),
            artifacts=_required_mapping(payload, "artifacts"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": self.status.value,
            "partial": self.partial,
            "error": self.error,
            "provenance": dict(self.provenance),
            "selection": dict(self.selection),
            "timing": dict(self.timing),
            "metrics": self.metrics.to_dict(),
            "valuation": self.valuation.to_dict(),
            "open_positions": [dict(position) for position in self.open_positions],
            "artifacts": dict(self.artifacts),
        }


def _required_mapping(
    payload: Mapping[str, object], key: str
) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"performance summary {key} must be an object")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"performance summary {key} must be text")
    return value


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"performance summary {key} must be text or null")
    return value


def _nonnegative_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"performance summary {key} must be nonnegative")
    return value


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"performance summary {key} must be boolean")
    return value
