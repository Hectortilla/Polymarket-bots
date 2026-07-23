"""Stable names and field contracts for performance result artifacts."""

from __future__ import annotations

from enum import StrEnum


RESULT_SCHEMA_VERSION = 1
DEFAULT_REPORT_INTERVAL_MS = 1_000
SUMMARY_FILE_NAME = "summary.json"
EQUITY_FILE_NAME = "equity.csv"
ORDERS_FILE_NAME = "orders.csv"


class EquityField(StrEnum):
    TIMESTAMP_MS = "timestamp_ms"
    SAMPLE_REASON = "sample_reason"
    CASH_USDC = "cash_usdc"
    MARKED_POSITION_VALUE_USDC = "marked_position_value_usdc"
    EQUITY_USDC = "equity_usdc"
    PNL_USDC = "pnl_usdc"
    FEES_USDC = "fees_usdc"
    EXPOSURE_USDC = "exposure_usdc"
    POSITION_COUNT = "position_count"
    VALUATION_STATUS = "valuation_status"


EQUITY_FIELDS = tuple(field.value for field in EquityField)


class OrderField(StrEnum):
    SUBMITTED_AT_MS = "submitted_at_ms"
    COMPLETED_AT_MS = "completed_at_ms"
    ORDER_ID = "order_id"
    MARKET_SLUG = "market_slug"
    CONDITION_ID = "condition_id"
    TOKEN_ID = "token_id"
    SIDE = "side"
    REQUESTED_PRICE = "requested_price"
    REQUESTED_SIZE = "requested_size"
    STATUS = "status"
    FILLED_SIZE = "filled_size"
    AVERAGE_PRICE = "average_price"
    FEE_USDC = "fee_usdc"
    REJECT_REASON = "reject_reason"
    REJECT_MESSAGE = "reject_message"
    STRATEGY_REASON = "strategy_reason"
    SOURCE_ID = "source_id"


ORDER_FIELDS = tuple(field.value for field in OrderField)


class PerformanceSummaryField(StrEnum):
    SCHEMA_VERSION = "schema_version"
    STATUS = "status"
    PARTIAL = "partial"
    ERROR = "error"
    PROVENANCE = "provenance"
    SELECTION = "selection"
    TIMING = "timing"
    METRICS = "metrics"
    VALUATION = "valuation"
    OPEN_POSITIONS = "open_positions"
    ARTIFACTS = "artifacts"


class PerformanceProvenanceField(StrEnum):
    KIND = "kind"
    BOT_SPEC = "bot_spec"
    CONFIGURATION = "configuration"
    SEED = "seed"
    ARCHIVE_SHA256 = "archive_sha256"
    ARCHIVE_SCHEMA_VERSION = "archive_schema_version"
    ARCHIVE_TARGET_IDENTITY = "archive_target_identity"


class PerformanceSelectionField(StrEnum):
    SESSION_ID = "session_id"
    START_MS = "start_ms"
    END_MS = "end_ms"
    MARKET_SLUGS = "market_slugs"
    REPLAY_CUTOFF_SEQUENCE = "replay_cutoff_sequence"
    SESSION_INTEGRITY_STATUS = "session_integrity_status"
    USES_PARTIAL_SESSION = "uses_partial_session"
    GAP_POLICY = "gap_policy"
    COVERAGE_GAP_IDS = "coverage_gap_ids"
    COVERAGE_GAP_COUNT = "coverage_gap_count"
    COVERAGE_GAP_DURATION_MS = "coverage_gap_duration_ms"
    COVERAGE_GAP_OPEN_COUNT = "coverage_gap_open_count"
    COVERAGE_GAP_AFFECTED_POSITION_TOKEN_IDS = (
        "coverage_gap_affected_position_token_ids"
    )
    COVERAGE_GAP_AFFECTED_POSITION_COUNT = "coverage_gap_affected_position_count"


class PerformanceTimingField(StrEnum):
    STARTED_AT_MS = "started_at_ms"
    ENDED_AT_MS = "ended_at_ms"
    VIRTUAL_DURATION_MS = "virtual_duration_ms"


class PerformanceMetricsField(StrEnum):
    INITIAL_CASH_USDC = "initial_cash_usdc"
    INITIAL_EQUITY_USDC = "initial_equity_usdc"
    FINAL_CASH_USDC = "final_cash_usdc"
    FINAL_MARKED_POSITION_VALUE_USDC = "final_marked_position_value_usdc"
    FINAL_EQUITY_USDC = "final_equity_usdc"
    GROSS_PNL_USDC = "gross_pnl_usdc"
    NET_PNL_USDC = "net_pnl_usdc"
    RETURN_FRACTION = "return"
    FEES_USDC = "fees_usdc"
    FILLED_NOTIONAL_USDC = "filled_notional_usdc"
    MAX_DRAWDOWN_USDC = "max_drawdown_usdc"
    MAX_DRAWDOWN_FRACTION = "max_drawdown_fraction"
    ORDER_COUNT = "order_count"
    FILL_COUNT = "fill_count"
    REJECTED_ORDER_COUNT = "rejected_order_count"
    COVERAGE_GAP_REJECTED_ORDER_COUNT = "coverage_gap_rejected_order_count"
    RESOLUTION_COUNT = "resolution_count"
    EVENT_COUNT = "event_count"
    DISPATCH_COUNT = "dispatch_count"
    ACCEPTED_DISPATCH_COUNT = "accepted_dispatch_count"
    SKIPPED_DISPATCH_COUNT = "skipped_dispatch_count"


class PerformanceValuationField(StrEnum):
    FINAL_STATUS = "final_status"
    HISTORY_STATUS = "history_status"
    DRAWDOWN_STATUS = "drawdown_status"
    COMPLETE = "complete"
    ESTIMATED = "estimated"
    SAMPLE_COUNT = "sample_count"
    AVAILABLE_SAMPLE_COUNT = "available_sample_count"
    STALE_SAMPLE_COUNT = "stale_sample_count"
    UNAVAILABLE_SAMPLE_COUNT = "unavailable_sample_count"


class PerformancePositionField(StrEnum):
    TOKEN_ID = "token_id"
    SIZE = "size"
    AVERAGE_ENTRY_PRICE = "average_entry_price"
    EXECUTABLE_MARK = "executable_mark"
    LAST_EXECUTABLE_MARK = "last_executable_mark"
    MARKET_VALUE_USDC = "market_value_usdc"
    VALUATION_STATUS = "valuation_status"


class PerformanceArtifactField(StrEnum):
    EQUITY = "equity"
    ORDERS = "orders"
