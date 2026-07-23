"""Structured data codecs for standard recording payloads."""

from __future__ import annotations

from typing import Any

from ..contracts.book import (
    BookBaselinePayload,
    BookChange,
    BookDeltaPayload,
    RecordedBookLevel,
    TickSizeChangePayload,
)
from ..contracts.gaps import CoverageGapPayload, CoverageGapReason
from ..contracts.market import (
    FeeScheduleMetadata,
    MarketEventMetadata,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
)
from ..contracts.payloads import PublicTradePayload, ResolutionPayload
from . import fields
from .parsing import (
    decimal_to_json,
    optional_boolean,
    optional_decimal_from_json,
    optional_integer,
    optional_text,
    require_array,
    require_boolean,
    require_decimal,
    require_exact_keys,
    require_integer,
    require_object,
    require_side,
    require_text,
    require_text_tuple,
)


def encode_market_metadata(payload: MarketMetadataPayload) -> dict[str, Any]:
    return {
        fields.ACCEPTING_ORDERS_FIELD: payload.accepting_orders,
        fields.ACTIVE_FIELD: payload.active,
        fields.ARCHIVED_FIELD: payload.archived,
        fields.CLOSED_FIELD: payload.closed,
        fields.CLOSED_AT_MS_FIELD: payload.closed_at_ms,
        fields.CONDITION_ID_FIELD: payload.condition_id,
        fields.END_AT_MS_FIELD: payload.end_at_ms,
        fields.EVENTS_FIELD: [
            {
                fields.EVENT_ID_FIELD: event.event_id,
                fields.SLUG_FIELD: event.slug,
                fields.TITLE_FIELD: event.title,
            }
            for event in payload.events
        ],
        fields.FEE_RATE_FIELD: str(payload.fee_rate),
        fields.FEE_SCHEDULE_FIELD: _fee_schedule_to_data(payload.fee_schedule),
        fields.FEE_TYPE_FIELD: payload.fee_type,
        fields.FEES_ENABLED_FIELD: payload.fees_enabled,
        fields.MARKET_ID_FIELD: payload.market_id,
        fields.MARKET_SLUG_FIELD: payload.market_slug,
        fields.MINIMUM_ORDER_SIZE_FIELD: decimal_to_json(payload.minimum_order_size),
        fields.MINIMUM_TICK_SIZE_FIELD: decimal_to_json(payload.minimum_tick_size),
        fields.NEG_RISK_FIELD: payload.neg_risk,
        fields.NEG_RISK_REQUEST_ID_FIELD: payload.neg_risk_request_id,
        fields.ORDER_BOOK_ENABLED_FIELD: payload.order_book_enabled,
        fields.OUTCOMES_FIELD: [
            {
                fields.LABEL_FIELD: outcome.label,
                fields.PRICE_FIELD: decimal_to_json(outcome.price),
                fields.TOKEN_ID_FIELD: outcome.token_id,
            }
            for outcome in payload.outcomes
        ],
        fields.QUESTION_FIELD: payload.question,
        fields.QUESTION_ID_FIELD: payload.question_id,
        fields.RESOLUTION_SOURCE_FIELD: payload.resolution_source,
        fields.RESOLUTION_STATUS_FIELD: payload.resolution_status,
        fields.RESOLVED_FIELD: payload.resolved,
        fields.RESOLVED_BY_FIELD: payload.resolved_by,
        fields.SECONDS_DELAY_FIELD: payload.seconds_delay,
        fields.START_AT_MS_FIELD: payload.start_at_ms,
        fields.RESOLUTION_WINNING_OUTCOME_FIELD: payload.winning_outcome,
        fields.RESOLUTION_WINNING_TOKEN_ID_FIELD: payload.winning_token_id,
    }


def _fee_schedule_to_data(
    fee_schedule: FeeScheduleMetadata | None,
) -> dict[str, Any] | None:
    if fee_schedule is None:
        return None
    return {
        fields.EXPONENT_FIELD: str(fee_schedule.exponent),
        fields.RATE_FIELD: str(fee_schedule.rate),
        fields.REBATE_RATE_FIELD: str(fee_schedule.rebate_rate),
        fields.TAKER_ONLY_FIELD: fee_schedule.taker_only,
    }


def encode_book_baseline(payload: BookBaselinePayload) -> dict[str, Any]:
    return {
        fields.ASKS_FIELD: [_level_to_data(level) for level in payload.asks],
        fields.BIDS_FIELD: [_level_to_data(level) for level in payload.bids],
        fields.SOURCE_HASH_FIELD: payload.source_hash,
        fields.TOKEN_ID_FIELD: payload.token_id,
    }


def _level_to_data(level: RecordedBookLevel) -> dict[str, str]:
    return {
        fields.PRICE_FIELD: str(level.price),
        fields.SIZE_FIELD: str(level.size),
    }


def _change_to_data(change: BookChange) -> dict[str, Any]:
    return {
        fields.BEST_ASK_FIELD: decimal_to_json(change.best_ask),
        fields.BEST_BID_FIELD: decimal_to_json(change.best_bid),
        fields.PRICE_FIELD: str(change.price),
        fields.SIDE_FIELD: change.side.value,
        fields.SIZE_FIELD: str(change.size),
        fields.SOURCE_HASH_FIELD: change.source_hash,
        fields.TOKEN_ID_FIELD: change.token_id,
    }


def decode_market_metadata(data: dict[str, Any]) -> MarketMetadataPayload:
    require_exact_keys(data, fields.MARKET_METADATA_FIELDS)
    events_data = require_array(data[fields.EVENTS_FIELD], "market events")
    outcomes_data = require_array(data[fields.OUTCOMES_FIELD], "market outcomes")
    events = tuple(_event_metadata_from_data(value) for value in events_data)
    outcomes = tuple(_outcome_metadata_from_data(value) for value in outcomes_data)
    if len(outcomes) != 2:
        raise ValueError("recording payload market outcomes must contain two values")
    return MarketMetadataPayload(
        market_id=require_text(data[fields.MARKET_ID_FIELD], "market ID"),
        condition_id=require_text(data[fields.CONDITION_ID_FIELD], "condition ID"),
        market_slug=require_text(data[fields.MARKET_SLUG_FIELD], "market slug"),
        question=require_text(data[fields.QUESTION_FIELD], "market question"),
        events=events,
        outcomes=(outcomes[0], outcomes[1]),
        active=optional_boolean(data[fields.ACTIVE_FIELD], "active"),
        closed=optional_boolean(data[fields.CLOSED_FIELD], "closed"),
        archived=optional_boolean(data[fields.ARCHIVED_FIELD], "archived"),
        start_at_ms=optional_integer(data[fields.START_AT_MS_FIELD], "start timestamp"),
        end_at_ms=optional_integer(data[fields.END_AT_MS_FIELD], "end timestamp"),
        closed_at_ms=optional_integer(
            data[fields.CLOSED_AT_MS_FIELD],
            "closed timestamp",
        ),
        order_book_enabled=optional_boolean(
            data[fields.ORDER_BOOK_ENABLED_FIELD],
            "order-book state",
        ),
        accepting_orders=optional_boolean(
            data[fields.ACCEPTING_ORDERS_FIELD],
            "accepting-orders state",
        ),
        minimum_tick_size=optional_decimal_from_json(
            data[fields.MINIMUM_TICK_SIZE_FIELD],
            "minimum tick size",
        ),
        minimum_order_size=optional_decimal_from_json(
            data[fields.MINIMUM_ORDER_SIZE_FIELD],
            "minimum order size",
        ),
        seconds_delay=optional_integer(
            data[fields.SECONDS_DELAY_FIELD],
            "seconds delay",
        ),
        neg_risk=optional_boolean(data[fields.NEG_RISK_FIELD], "negative-risk state"),
        fees_enabled=optional_boolean(data[fields.FEES_ENABLED_FIELD], "fee state"),
        fee_type=optional_text(data[fields.FEE_TYPE_FIELD], "fee type"),
        fee_schedule=_fee_schedule_from_data(data[fields.FEE_SCHEDULE_FIELD]),
        fee_rate=require_decimal(data[fields.FEE_RATE_FIELD], "fee rate"),
        question_id=optional_text(data[fields.QUESTION_ID_FIELD], "question ID"),
        neg_risk_request_id=optional_text(
            data[fields.NEG_RISK_REQUEST_ID_FIELD],
            "negative-risk request ID",
        ),
        resolution_status=optional_text(
            data[fields.RESOLUTION_STATUS_FIELD],
            "resolution status",
        ),
        resolution_source=optional_text(
            data[fields.RESOLUTION_SOURCE_FIELD],
            "resolution source",
        ),
        resolved_by=optional_text(data[fields.RESOLVED_BY_FIELD], "resolver"),
        resolved=require_boolean(data[fields.RESOLVED_FIELD], "resolved state"),
        winning_token_id=optional_text(
            data[fields.RESOLUTION_WINNING_TOKEN_ID_FIELD],
            "winning token ID",
        ),
        winning_outcome=optional_text(
            data[fields.RESOLUTION_WINNING_OUTCOME_FIELD],
            "winning outcome",
        ),
    )


def _event_metadata_from_data(value: object) -> MarketEventMetadata:
    data = require_object(value, "market event")
    require_exact_keys(data, fields.MARKET_EVENT_FIELDS)
    return MarketEventMetadata(
        event_id=require_text(data[fields.EVENT_ID_FIELD], "event ID"),
        slug=optional_text(data[fields.SLUG_FIELD], "event slug"),
        title=optional_text(data[fields.TITLE_FIELD], "event title"),
    )


def _outcome_metadata_from_data(value: object) -> MarketOutcomeMetadata:
    data = require_object(value, "market outcome")
    require_exact_keys(data, fields.MARKET_OUTCOME_FIELDS)
    return MarketOutcomeMetadata(
        label=require_text(data[fields.LABEL_FIELD], "outcome label"),
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "outcome token ID"),
        price=optional_decimal_from_json(data[fields.PRICE_FIELD], "outcome price"),
    )


def _fee_schedule_from_data(value: object) -> FeeScheduleMetadata | None:
    if value is None:
        return None
    data = require_object(value, "fee schedule")
    require_exact_keys(data, fields.FEE_SCHEDULE_FIELDS)
    return FeeScheduleMetadata(
        exponent=require_decimal(data[fields.EXPONENT_FIELD], "fee exponent"),
        rate=require_decimal(data[fields.RATE_FIELD], "fee rate"),
        taker_only=require_boolean(data[fields.TAKER_ONLY_FIELD], "taker-only state"),
        rebate_rate=require_decimal(data[fields.REBATE_RATE_FIELD], "rebate rate"),
    )


def decode_book_baseline(data: dict[str, Any]) -> BookBaselinePayload:
    require_exact_keys(data, fields.BOOK_BASELINE_FIELDS)
    return BookBaselinePayload(
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "book token ID"),
        bids=tuple(
            _level_from_data(value)
            for value in require_array(data[fields.BIDS_FIELD], "book bids")
        ),
        asks=tuple(
            _level_from_data(value)
            for value in require_array(data[fields.ASKS_FIELD], "book asks")
        ),
        source_hash=optional_text(data[fields.SOURCE_HASH_FIELD], "book source hash"),
    )


def _level_from_data(value: object) -> RecordedBookLevel:
    data = require_object(value, "book level")
    require_exact_keys(data, fields.BOOK_LEVEL_FIELDS)
    return RecordedBookLevel(
        price=require_decimal(data[fields.PRICE_FIELD], "book price"),
        size=require_decimal(data[fields.SIZE_FIELD], "book size"),
    )


def decode_book_delta(data: dict[str, Any]) -> BookDeltaPayload:
    require_exact_keys(data, fields.BOOK_DELTA_FIELDS)
    return BookDeltaPayload(
        changes=tuple(
            _change_from_data(value)
            for value in require_array(data[fields.CHANGES_FIELD], "book changes")
        )
    )


def _change_from_data(value: object) -> BookChange:
    data = require_object(value, "book change")
    require_exact_keys(data, fields.BOOK_CHANGE_FIELDS)
    return BookChange(
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "book change token ID"),
        side=require_side(data[fields.SIDE_FIELD]),
        price=require_decimal(data[fields.PRICE_FIELD], "book change price"),
        size=require_decimal(data[fields.SIZE_FIELD], "book change size"),
        source_hash=optional_text(data[fields.SOURCE_HASH_FIELD], "change source hash"),
        best_bid=optional_decimal_from_json(data[fields.BEST_BID_FIELD], "best bid"),
        best_ask=optional_decimal_from_json(data[fields.BEST_ASK_FIELD], "best ask"),
    )


def decode_public_trade(data: dict[str, Any]) -> PublicTradePayload:
    require_exact_keys(data, fields.PUBLIC_TRADE_FIELDS)
    return PublicTradePayload(
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "public trade token ID"),
        price=require_decimal(data[fields.PRICE_FIELD], "public trade price"),
        size=require_decimal(data[fields.SIZE_FIELD], "public trade size"),
        side=require_side(data[fields.SIDE_FIELD]),
        fee_rate_bps=optional_decimal_from_json(
            data[fields.FEE_RATE_BPS_FIELD],
            "public trade fee rate",
        ),
        transaction_hash=optional_text(
            data[fields.TRANSACTION_HASH_FIELD],
            "transaction hash",
        ),
    )


def decode_tick_size_change(data: dict[str, Any]) -> TickSizeChangePayload:
    require_exact_keys(data, fields.TICK_SIZE_CHANGE_FIELDS)
    return TickSizeChangePayload(
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "tick-size token ID"),
        old_tick_size=optional_decimal_from_json(
            data[fields.OLD_TICK_SIZE_FIELD],
            "old tick size",
        ),
        new_tick_size=require_decimal(
            data[fields.NEW_TICK_SIZE_FIELD],
            "new tick size",
        ),
    )


def decode_resolution(data: dict[str, Any]) -> ResolutionPayload:
    require_exact_keys(data, fields.RESOLUTION_FIELDS)
    token_ids = require_text_tuple(
        data[fields.TOKEN_IDS_FIELD],
        "resolution token IDs",
    )
    if len(token_ids) != 2:
        raise ValueError("recording payload resolution requires two token IDs")
    return ResolutionPayload(
        token_ids=(token_ids[0], token_ids[1]),
        winning_token_id=require_text(
            data[fields.RESOLUTION_WINNING_TOKEN_ID_FIELD],
            "winning token ID",
        ),
        winning_outcome=require_text(
            data[fields.RESOLUTION_WINNING_OUTCOME_FIELD],
            "winning outcome",
        ),
        source=require_text(data[fields.RESOLUTION_SOURCE_FIELD], "resolution source"),
        resolution_id=optional_text(
            data[fields.RESOLUTION_ID_FIELD],
            "resolution ID",
        ),
    )


def decode_coverage_gap(data: dict[str, Any]) -> CoverageGapPayload:
    require_exact_keys(data, fields.COVERAGE_GAP_FIELDS)
    return CoverageGapPayload(
        reason=CoverageGapReason(
            require_text(data[fields.REASON_FIELD], "coverage gap reason")
        ),
        started_at_ms=require_integer(
            data[fields.STARTED_AT_MS_FIELD],
            "coverage gap start",
        ),
        ended_at_ms=optional_integer(
            data[fields.ENDED_AT_MS_FIELD],
            "coverage gap end",
        ),
        affected_condition_ids=require_text_tuple(
            data[fields.AFFECTED_CONDITION_IDS_FIELD],
            "affected condition IDs",
        ),
        affected_market_slugs=require_text_tuple(
            data[fields.AFFECTED_MARKET_SLUGS_FIELD],
            "affected market slugs",
        ),
        affected_token_ids=require_text_tuple(
            data[fields.AFFECTED_TOKEN_IDS_FIELD],
            "affected token IDs",
        ),
        details=optional_text(data[fields.DETAILS_FIELD], "coverage gap details"),
    )


def encode_book_delta(payload: BookDeltaPayload) -> dict[str, Any]:
    return {
        fields.CHANGES_FIELD: [_change_to_data(change) for change in payload.changes]
    }


def encode_public_trade(payload: PublicTradePayload) -> dict[str, Any]:
    return {
        fields.FEE_RATE_BPS_FIELD: decimal_to_json(payload.fee_rate_bps),
        fields.PRICE_FIELD: str(payload.price),
        fields.SIDE_FIELD: payload.side.value,
        fields.SIZE_FIELD: str(payload.size),
        fields.TOKEN_ID_FIELD: payload.token_id,
        fields.TRANSACTION_HASH_FIELD: payload.transaction_hash,
    }


def encode_tick_size_change(payload: TickSizeChangePayload) -> dict[str, Any]:
    return {
        fields.NEW_TICK_SIZE_FIELD: str(payload.new_tick_size),
        fields.OLD_TICK_SIZE_FIELD: decimal_to_json(payload.old_tick_size),
        fields.TOKEN_ID_FIELD: payload.token_id,
    }


def encode_resolution(payload: ResolutionPayload) -> dict[str, Any]:
    return {
        fields.RESOLUTION_ID_FIELD: payload.resolution_id,
        fields.RESOLUTION_SOURCE_FIELD: payload.source,
        fields.TOKEN_IDS_FIELD: list(payload.token_ids),
        fields.RESOLUTION_WINNING_OUTCOME_FIELD: payload.winning_outcome,
        fields.RESOLUTION_WINNING_TOKEN_ID_FIELD: payload.winning_token_id,
    }


def encode_coverage_gap(payload: CoverageGapPayload) -> dict[str, Any]:
    return {
        fields.AFFECTED_CONDITION_IDS_FIELD: list(payload.affected_condition_ids),
        fields.AFFECTED_MARKET_SLUGS_FIELD: list(payload.affected_market_slugs),
        fields.AFFECTED_TOKEN_IDS_FIELD: list(payload.affected_token_ids),
        fields.DETAILS_FIELD: payload.details,
        fields.ENDED_AT_MS_FIELD: payload.ended_at_ms,
        fields.REASON_FIELD: payload.reason.value,
        fields.STARTED_AT_MS_FIELD: payload.started_at_ms,
    }
