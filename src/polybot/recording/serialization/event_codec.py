"""Trade, resolution, and coverage-gap recording payload codecs."""

from __future__ import annotations

from typing import Any

from ..contracts.gaps import CoverageGapPayload, CoverageGapReason
from ..contracts.payloads import PublicTradePayload, ResolutionPayload
from . import fields
from .parsing import (
    decimal_to_json,
    optional_decimal_from_json,
    optional_integer,
    optional_text,
    require_decimal,
    require_exact_keys,
    require_integer,
    require_side,
    require_text,
    require_text_tuple,
)


def encode_public_trade(payload: PublicTradePayload) -> dict[str, Any]:
    return {
        fields.FEE_RATE_BPS_FIELD: decimal_to_json(payload.fee_rate_bps),
        fields.PRICE_FIELD: str(payload.price),
        fields.SIDE_FIELD: payload.side.value,
        fields.SIZE_FIELD: str(payload.size),
        fields.TOKEN_ID_FIELD: payload.token_id,
        fields.TRANSACTION_HASH_FIELD: payload.transaction_hash,
    }


def decode_public_trade(data: dict[str, Any]) -> PublicTradePayload:
    require_exact_keys(data, fields.PUBLIC_TRADE_FIELDS)
    return PublicTradePayload(
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "public trade token ID"),
        price=require_decimal(data[fields.PRICE_FIELD], "public trade price"),
        size=require_decimal(data[fields.SIZE_FIELD], "public trade size"),
        side=require_side(data[fields.SIDE_FIELD]),
        fee_rate_bps=optional_decimal_from_json(
            data[fields.FEE_RATE_BPS_FIELD], "public trade fee rate"
        ),
        transaction_hash=optional_text(
            data[fields.TRANSACTION_HASH_FIELD], "transaction hash"
        ),
    )


def encode_resolution(payload: ResolutionPayload) -> dict[str, Any]:
    return {
        fields.RESOLUTION_ID_FIELD: payload.resolution_id,
        fields.RESOLUTION_PAYLOAD_SOURCE_FIELD: payload.source,
        fields.TOKEN_IDS_FIELD: list(payload.token_ids),
        fields.RESOLUTION_WINNING_OUTCOME_FIELD: payload.winning_outcome,
        fields.RESOLUTION_WINNING_TOKEN_ID_FIELD: payload.winning_token_id,
    }


def decode_resolution(data: dict[str, Any]) -> ResolutionPayload:
    require_exact_keys(data, fields.RESOLUTION_FIELDS)
    token_ids = require_text_tuple(data[fields.TOKEN_IDS_FIELD], "resolution token IDs")
    if len(token_ids) != 2:
        raise ValueError("recording payload resolution requires two token IDs")
    return ResolutionPayload(
        token_ids=(token_ids[0], token_ids[1]),
        winning_token_id=require_text(
            data[fields.RESOLUTION_WINNING_TOKEN_ID_FIELD], "winning token ID"
        ),
        winning_outcome=require_text(
            data[fields.RESOLUTION_WINNING_OUTCOME_FIELD], "winning outcome"
        ),
        source=require_text(
            data[fields.RESOLUTION_PAYLOAD_SOURCE_FIELD], "resolution source"
        ),
        resolution_id=optional_text(
            data[fields.RESOLUTION_ID_FIELD], "resolution ID"
        ),
    )


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


def decode_coverage_gap(data: dict[str, Any]) -> CoverageGapPayload:
    require_exact_keys(data, fields.COVERAGE_GAP_FIELDS)
    return CoverageGapPayload(
        reason=CoverageGapReason(
            require_text(data[fields.REASON_FIELD], "coverage gap reason")
        ),
        started_at_ms=require_integer(
            data[fields.STARTED_AT_MS_FIELD], "coverage gap start"
        ),
        ended_at_ms=optional_integer(
            data[fields.ENDED_AT_MS_FIELD], "coverage gap end"
        ),
        affected_condition_ids=require_text_tuple(
            data[fields.AFFECTED_CONDITION_IDS_FIELD], "affected condition IDs"
        ),
        affected_market_slugs=require_text_tuple(
            data[fields.AFFECTED_MARKET_SLUGS_FIELD], "affected market slugs"
        ),
        affected_token_ids=require_text_tuple(
            data[fields.AFFECTED_TOKEN_IDS_FIELD], "affected token IDs"
        ),
        details=optional_text(data[fields.DETAILS_FIELD], "coverage gap details"),
    )
