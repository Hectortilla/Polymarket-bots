"""Canonical JSON field names and exact schemas for recording payloads."""

from typing import Final

from polybot.framework.events.resolution_fields import (
    RESOLUTION_WINNING_OUTCOME_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
)


ACCEPTING_ORDERS_FIELD: Final = "accepting_orders"
ACTIVE_FIELD: Final = "active"
ACTUAL_FINGERPRINT_FIELD: Final = "actual_fingerprint"
ADVERTISED_BEST_ASK_FIELD: Final = "advertised_best_ask"
ADVERTISED_BEST_BID_FIELD: Final = "advertised_best_bid"
AFFECTED_CONDITION_IDS_FIELD: Final = "affected_condition_ids"
AFFECTED_MARKET_SLUGS_FIELD: Final = "affected_market_slugs"
AFFECTED_TOKEN_IDS_FIELD: Final = "affected_token_ids"
ARCHIVED_FIELD: Final = "archived"
ASKS_FIELD: Final = "asks"
BEST_ASK_FIELD: Final = "best_ask"
BEST_BID_FIELD: Final = "best_bid"
BIDS_FIELD: Final = "bids"
BOOK_DIAGNOSTICS_FIELD: Final = "book_diagnostics"
CHANGES_FIELD: Final = "changes"
CLOSED_AT_MS_FIELD: Final = "closed_at_ms"
CLOSED_FIELD: Final = "closed"
CONDITION_ID_FIELD: Final = "condition_id"
DETAILS_FIELD: Final = "details"
DROPPED_COUNT_AFTER_FIELD: Final = "dropped_count_after"
DROPPED_COUNT_BEFORE_FIELD: Final = "dropped_count_before"
ELAPSED_MS_FIELD: Final = "elapsed_ms"
ENDED_AT_MS_FIELD: Final = "ended_at_ms"
END_AT_MS_FIELD: Final = "end_at_ms"
EVENT_ID_FIELD: Final = "event_id"
EVENTS_FIELD: Final = "events"
EXPECTED_FINGERPRINT_FIELD: Final = "expected_fingerprint"
EXPONENT_FIELD: Final = "exponent"
FAILURE_KIND_FIELD: Final = "failure_kind"
FEE_RATE_BPS_FIELD: Final = "fee_rate_bps"
FEE_RATE_FIELD: Final = "fee_rate"
FEE_SCHEDULE_FIELD: Final = "fee_schedule"
FEE_TYPE_FIELD: Final = "fee_type"
FEES_ENABLED_FIELD: Final = "fees_enabled"
FRAGMENTS_FIELD: Final = "fragments"
IDENTITY_FIELD: Final = "identity"
LABEL_FIELD: Final = "label"
MARKET_ID_FIELD: Final = "market_id"
MARKET_SLUG_FIELD: Final = "market_slug"
MINIMUM_ORDER_SIZE_FIELD: Final = "minimum_order_size"
MINIMUM_TICK_SIZE_FIELD: Final = "minimum_tick_size"
NEG_RISK_FIELD: Final = "neg_risk"
NEG_RISK_REQUEST_ID_FIELD: Final = "neg_risk_request_id"
NEW_TICK_SIZE_FIELD: Final = "new_tick_size"
OLD_TICK_SIZE_FIELD: Final = "old_tick_size"
ORDER_BOOK_ENABLED_FIELD: Final = "order_book_enabled"
OUTCOMES_FIELD: Final = "outcomes"
PAYLOAD_FIELD: Final = "payload"
PAYLOAD_KIND_FIELD: Final = "payload_kind"
PRICE_FIELD: Final = "price"
PROJECTED_BEST_ASK_FIELD: Final = "projected_best_ask"
PROJECTED_BEST_BID_FIELD: Final = "projected_best_bid"
QUESTION_FIELD: Final = "question"
QUESTION_ID_FIELD: Final = "question_id"
RATE_FIELD: Final = "rate"
REASON_FIELD: Final = "reason"
REBATE_RATE_FIELD: Final = "rebate_rate"
RESOLUTION_ID_FIELD: Final = "resolution_id"
MARKET_RESOLUTION_SOURCE_FIELD: Final = "resolution_source"
RESOLUTION_PAYLOAD_SOURCE_FIELD: Final = "resolution_source"
RESOLUTION_STATUS_FIELD: Final = "resolution_status"
RESOLVED_BY_FIELD: Final = "resolved_by"
RESOLVED_FIELD: Final = "resolved"
ROLE_FIELD: Final = "role"
SECONDS_DELAY_FIELD: Final = "seconds_delay"
SIDE_FIELD: Final = "side"
SIZE_FIELD: Final = "size"
SLUG_FIELD: Final = "slug"
SOURCE_HASHES_FIELD: Final = "source_hashes"
SOURCE_HASH_FIELD: Final = "source_hash"
SOURCE_TIMESTAMP_MS_FIELD: Final = "source_timestamp_ms"
STARTED_AT_MS_FIELD: Final = "started_at_ms"
START_AT_MS_FIELD: Final = "start_at_ms"
TAKER_ONLY_FIELD: Final = "taker_only"
TITLE_FIELD: Final = "title"
TOKEN_IDS_FIELD: Final = "token_ids"
TOKEN_ID_FIELD: Final = "token_id"
TRANSACTION_HASH_FIELD: Final = "transaction_hash"


MARKET_METADATA_FIELDS: Final[frozenset[str]] = frozenset(
    {
        ACCEPTING_ORDERS_FIELD,
        ACTIVE_FIELD,
        ARCHIVED_FIELD,
        CLOSED_AT_MS_FIELD,
        CLOSED_FIELD,
        CONDITION_ID_FIELD,
        END_AT_MS_FIELD,
        EVENTS_FIELD,
        FEE_RATE_FIELD,
        FEE_SCHEDULE_FIELD,
        FEE_TYPE_FIELD,
        FEES_ENABLED_FIELD,
        MARKET_ID_FIELD,
        MARKET_SLUG_FIELD,
        MINIMUM_ORDER_SIZE_FIELD,
        MINIMUM_TICK_SIZE_FIELD,
        NEG_RISK_FIELD,
        NEG_RISK_REQUEST_ID_FIELD,
        ORDER_BOOK_ENABLED_FIELD,
        OUTCOMES_FIELD,
        QUESTION_FIELD,
        QUESTION_ID_FIELD,
        MARKET_RESOLUTION_SOURCE_FIELD,
        RESOLUTION_STATUS_FIELD,
        RESOLVED_BY_FIELD,
        RESOLVED_FIELD,
        SECONDS_DELAY_FIELD,
        START_AT_MS_FIELD,
        RESOLUTION_WINNING_OUTCOME_FIELD,
        RESOLUTION_WINNING_TOKEN_ID_FIELD,
    }
)
MARKET_EVENT_FIELDS: Final[frozenset[str]] = frozenset(
    {EVENT_ID_FIELD, SLUG_FIELD, TITLE_FIELD}
)
MARKET_OUTCOME_FIELDS: Final[frozenset[str]] = frozenset(
    {LABEL_FIELD, PRICE_FIELD, TOKEN_ID_FIELD}
)
FEE_SCHEDULE_FIELDS: Final[frozenset[str]] = frozenset(
    {EXPONENT_FIELD, RATE_FIELD, REBATE_RATE_FIELD, TAKER_ONLY_FIELD}
)
BOOK_BASELINE_FIELDS: Final[frozenset[str]] = frozenset(
    {ASKS_FIELD, BIDS_FIELD, SOURCE_HASH_FIELD, TOKEN_ID_FIELD}
)
BOOK_LEVEL_FIELDS: Final[frozenset[str]] = frozenset({PRICE_FIELD, SIZE_FIELD})
BOOK_DELTA_FIELDS: Final[frozenset[str]] = frozenset({CHANGES_FIELD})
BOOK_CHANGE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        BEST_ASK_FIELD,
        BEST_BID_FIELD,
        PRICE_FIELD,
        SIDE_FIELD,
        SIZE_FIELD,
        SOURCE_HASH_FIELD,
        TOKEN_ID_FIELD,
    }
)
PUBLIC_TRADE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        FEE_RATE_BPS_FIELD,
        PRICE_FIELD,
        SIDE_FIELD,
        SIZE_FIELD,
        TOKEN_ID_FIELD,
        TRANSACTION_HASH_FIELD,
    }
)
TICK_SIZE_CHANGE_FIELDS: Final[frozenset[str]] = frozenset(
    {NEW_TICK_SIZE_FIELD, OLD_TICK_SIZE_FIELD, TOKEN_ID_FIELD}
)
RESOLUTION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        RESOLUTION_ID_FIELD,
        RESOLUTION_PAYLOAD_SOURCE_FIELD,
        TOKEN_IDS_FIELD,
        RESOLUTION_WINNING_OUTCOME_FIELD,
        RESOLUTION_WINNING_TOKEN_ID_FIELD,
    }
)
COVERAGE_GAP_FIELDS: Final[frozenset[str]] = frozenset(
    {
        AFFECTED_CONDITION_IDS_FIELD,
        AFFECTED_MARKET_SLUGS_FIELD,
        AFFECTED_TOKEN_IDS_FIELD,
        DETAILS_FIELD,
        ENDED_AT_MS_FIELD,
        REASON_FIELD,
        STARTED_AT_MS_FIELD,
    }
)
CAPTURE_ANOMALY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        ACTUAL_FINGERPRINT_FIELD,
        BOOK_DIAGNOSTICS_FIELD,
        DETAILS_FIELD,
        DROPPED_COUNT_AFTER_FIELD,
        DROPPED_COUNT_BEFORE_FIELD,
        ELAPSED_MS_FIELD,
        EXPECTED_FINGERPRINT_FIELD,
        FAILURE_KIND_FIELD,
        FRAGMENTS_FIELD,
    }
)
REVISION_FINGERPRINT_FIELDS: Final[frozenset[str]] = frozenset(
    {CONDITION_ID_FIELD, SOURCE_HASHES_FIELD, SOURCE_TIMESTAMP_MS_FIELD}
)
REVISION_SOURCE_HASH_FIELDS: Final[frozenset[str]] = frozenset(
    {SOURCE_HASH_FIELD, TOKEN_ID_FIELD}
)
CAPTURE_FRAGMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        IDENTITY_FIELD,
        PAYLOAD_FIELD,
        PAYLOAD_KIND_FIELD,
        ROLE_FIELD,
        SOURCE_TIMESTAMP_MS_FIELD,
    }
)
MARKET_IDENTITY_FIELDS: Final[frozenset[str]] = frozenset(
    {CONDITION_ID_FIELD, MARKET_SLUG_FIELD, TOKEN_ID_FIELD}
)
CAPTURE_BOOK_DIAGNOSTICS_FIELDS: Final[frozenset[str]] = frozenset(
    {
        ADVERTISED_BEST_ASK_FIELD,
        ADVERTISED_BEST_BID_FIELD,
        PROJECTED_BEST_ASK_FIELD,
        PROJECTED_BEST_BID_FIELD,
        TOKEN_ID_FIELD,
    }
)
