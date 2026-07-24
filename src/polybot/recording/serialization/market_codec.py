"""Market-metadata recording payload codecs."""

from __future__ import annotations

from typing import Any

from ..contracts.market import (
    FeeScheduleMetadata,
    MarketEventMetadata,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
)
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
    require_object,
    require_text,
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
        fields.FEE_SCHEDULE_FIELD: _encode_fee_schedule(payload.fee_schedule),
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
        fields.MARKET_RESOLUTION_SOURCE_FIELD: payload.resolution_source,
        fields.RESOLUTION_STATUS_FIELD: payload.resolution_status,
        fields.RESOLVED_FIELD: payload.resolved,
        fields.RESOLVED_BY_FIELD: payload.resolved_by,
        fields.SECONDS_DELAY_FIELD: payload.seconds_delay,
        fields.START_AT_MS_FIELD: payload.start_at_ms,
        fields.RESOLUTION_WINNING_OUTCOME_FIELD: payload.winning_outcome,
        fields.RESOLUTION_WINNING_TOKEN_ID_FIELD: payload.winning_token_id,
    }


def decode_market_metadata(data: dict[str, Any]) -> MarketMetadataPayload:
    require_exact_keys(data, fields.MARKET_METADATA_FIELDS)
    events = tuple(
        _decode_event(value)
        for value in require_array(data[fields.EVENTS_FIELD], "market events")
    )
    outcomes = tuple(
        _decode_outcome(value)
        for value in require_array(data[fields.OUTCOMES_FIELD], "market outcomes")
    )
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
            data[fields.CLOSED_AT_MS_FIELD], "closed timestamp"
        ),
        order_book_enabled=optional_boolean(
            data[fields.ORDER_BOOK_ENABLED_FIELD], "order-book state"
        ),
        accepting_orders=optional_boolean(
            data[fields.ACCEPTING_ORDERS_FIELD], "accepting-orders state"
        ),
        minimum_tick_size=optional_decimal_from_json(
            data[fields.MINIMUM_TICK_SIZE_FIELD], "minimum tick size"
        ),
        minimum_order_size=optional_decimal_from_json(
            data[fields.MINIMUM_ORDER_SIZE_FIELD], "minimum order size"
        ),
        seconds_delay=optional_integer(
            data[fields.SECONDS_DELAY_FIELD], "seconds delay"
        ),
        neg_risk=optional_boolean(data[fields.NEG_RISK_FIELD], "negative-risk state"),
        fees_enabled=optional_boolean(data[fields.FEES_ENABLED_FIELD], "fee state"),
        fee_type=optional_text(data[fields.FEE_TYPE_FIELD], "fee type"),
        fee_schedule=_decode_fee_schedule(data[fields.FEE_SCHEDULE_FIELD]),
        fee_rate=require_decimal(data[fields.FEE_RATE_FIELD], "fee rate"),
        question_id=optional_text(data[fields.QUESTION_ID_FIELD], "question ID"),
        neg_risk_request_id=optional_text(
            data[fields.NEG_RISK_REQUEST_ID_FIELD], "negative-risk request ID"
        ),
        resolution_status=optional_text(
            data[fields.RESOLUTION_STATUS_FIELD], "resolution status"
        ),
        resolution_source=optional_text(
            data[fields.MARKET_RESOLUTION_SOURCE_FIELD], "resolution source"
        ),
        resolved_by=optional_text(data[fields.RESOLVED_BY_FIELD], "resolver"),
        resolved=require_boolean(data[fields.RESOLVED_FIELD], "resolved state"),
        winning_token_id=optional_text(
            data[fields.RESOLUTION_WINNING_TOKEN_ID_FIELD], "winning token ID"
        ),
        winning_outcome=optional_text(
            data[fields.RESOLUTION_WINNING_OUTCOME_FIELD], "winning outcome"
        ),
    )


def _encode_fee_schedule(
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


def _decode_event(value: object) -> MarketEventMetadata:
    data = require_object(value, "market event")
    require_exact_keys(data, fields.MARKET_EVENT_FIELDS)
    return MarketEventMetadata(
        event_id=require_text(data[fields.EVENT_ID_FIELD], "event ID"),
        slug=optional_text(data[fields.SLUG_FIELD], "event slug"),
        title=optional_text(data[fields.TITLE_FIELD], "event title"),
    )


def _decode_outcome(value: object) -> MarketOutcomeMetadata:
    data = require_object(value, "market outcome")
    require_exact_keys(data, fields.MARKET_OUTCOME_FIELDS)
    return MarketOutcomeMetadata(
        label=require_text(data[fields.LABEL_FIELD], "outcome label"),
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "outcome token ID"),
        price=optional_decimal_from_json(data[fields.PRICE_FIELD], "outcome price"),
    )


def _decode_fee_schedule(value: object) -> FeeScheduleMetadata | None:
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
