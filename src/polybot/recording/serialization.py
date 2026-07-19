"""Canonical JSON serialization for recording contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from polybot.framework.events import Side
from polybot.persistence.json_codec import loads_json

from .contracts import (
    BookBaselinePayload,
    BookChange,
    BookDeltaPayload,
    CaptureAnomalyFragment,
    CaptureAnomalyPayload,
    CaptureBookDiagnostics,
    CaptureFailureKind,
    CaptureFragmentRole,
    CoverageGapPayload,
    CoverageGapReason,
    FeeScheduleMetadata,
    MarketIdentity,
    MarketEventMetadata,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
    PublicTradePayload,
    RecordedBookLevel,
    RecordedPayload,
    RECORDED_PAYLOAD_TYPES,
    RevisionFingerprint,
    ResolutionPayload,
    TickSizeChangePayload,
)


class PayloadKind(StrEnum):
    MARKET_METADATA = "market_metadata"
    BOOK_BASELINE = "book_baseline"
    BOOK_DELTA = "book_delta"
    PUBLIC_TRADE = "public_trade"
    TICK_SIZE_CHANGE = "tick_size_change"
    RESOLUTION = "resolution"
    COVERAGE_GAP = "coverage_gap"


def payload_kind(payload: RecordedPayload) -> PayloadKind:
    return _codec_for_payload(payload).kind


def payload_json(payload: RecordedPayload) -> str:
    return canonical_json(_payload_to_data(payload))


def payload_from_json(kind: str | PayloadKind, raw_json: str) -> RecordedPayload:
    try:
        normalized_kind = PayloadKind(kind)
    except (TypeError, ValueError) as error:
        raise ValueError(f"unsupported recording payload kind: {kind!r}") from error
    data = _load_object(raw_json)
    try:
        return _CODEC_BY_KIND[normalized_kind].decode(data)
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        if isinstance(error, ValueError) and str(error).startswith("recording payload"):
            raise
        raise ValueError(
            f"recording payload {normalized_kind.value!r} is malformed"
        ) from error


def capture_anomaly_json(anomaly: CaptureAnomalyPayload) -> str:
    if not isinstance(anomaly, CaptureAnomalyPayload):
        raise ValueError("capture anomaly payload is invalid")
    return canonical_json(_capture_anomaly_to_data(anomaly))


def capture_anomaly_from_json(raw_json: str) -> CaptureAnomalyPayload:
    data = _load_object(raw_json)
    try:
        return _capture_anomaly_from_data(data)
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        if isinstance(error, ValueError) and str(error).startswith(
            "recording capture anomaly"
        ):
            raise
        raise ValueError("recording capture anomaly is malformed") from error


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("recording payload is not JSON serializable") from error


def text_tuple_json(values: tuple[str, ...]) -> str:
    return canonical_json(list(values))


def text_tuple_from_json(raw_json: str, name: str) -> tuple[str, ...]:
    value = _load_json(raw_json)
    if not isinstance(value, list):
        raise ValueError(f"recording {name} must be a JSON array")
    return tuple(_text(item, name) for item in value)


def _payload_to_data(payload: RecordedPayload) -> dict[str, Any]:
    return _codec_for_payload(payload).encode(payload)


def event_token_ids(payload: RecordedPayload) -> tuple[str, ...]:
    return _codec_for_payload(payload).token_ids(payload)


def payload_kind_sql_literals() -> str:
    """Return the discriminator literals accepted by the SQLite schema."""
    return ", ".join(f"'{codec.kind.value}'" for codec in PAYLOAD_CODECS)


def _capture_anomaly_to_data(anomaly: CaptureAnomalyPayload) -> dict[str, Any]:
    return {
        "actual_fingerprint": _fingerprint_to_data(anomaly.actual_fingerprint),
        "book_diagnostics": [
            _book_diagnostics_to_data(diagnostics)
            for diagnostics in anomaly.book_diagnostics
        ],
        "details": anomaly.details,
        "dropped_count_after": anomaly.dropped_count_after,
        "dropped_count_before": anomaly.dropped_count_before,
        "elapsed_ms": anomaly.elapsed_ms,
        "expected_fingerprint": _fingerprint_to_data(
            anomaly.expected_fingerprint
        ),
        "failure_kind": anomaly.failure_kind.value,
        "fragments": [
            _capture_fragment_to_data(fragment) for fragment in anomaly.fragments
        ],
    }


def _fingerprint_to_data(
    fingerprint: RevisionFingerprint | None,
) -> dict[str, Any] | None:
    if fingerprint is None:
        return None
    return {
        "condition_id": fingerprint.condition_id,
        "source_hashes": [
            {"source_hash": source_hash, "token_id": token_id}
            for token_id, source_hash in fingerprint.source_hashes
        ],
        "source_timestamp_ms": fingerprint.source_timestamp_ms,
    }


def _capture_fragment_to_data(
    fragment: CaptureAnomalyFragment,
) -> dict[str, Any]:
    return {
        "identity": _identity_to_data(fragment.identity),
        "payload": _payload_to_data(fragment.payload),
        "payload_kind": payload_kind(fragment.payload).value,
        "role": fragment.role.value,
        "source_timestamp_ms": fragment.source_timestamp_ms,
    }


def _identity_to_data(identity: MarketIdentity) -> dict[str, str | None]:
    return {
        "condition_id": identity.condition_id,
        "market_slug": identity.market_slug,
        "token_id": identity.token_id,
    }


def _book_diagnostics_to_data(
    diagnostics: CaptureBookDiagnostics,
) -> dict[str, str | None]:
    return {
        "advertised_best_ask": _optional_decimal(
            diagnostics.advertised_best_ask
        ),
        "advertised_best_bid": _optional_decimal(
            diagnostics.advertised_best_bid
        ),
        "projected_best_ask": _optional_decimal(
            diagnostics.projected_best_ask
        ),
        "projected_best_bid": _optional_decimal(
            diagnostics.projected_best_bid
        ),
        "token_id": diagnostics.token_id,
    }


def _metadata_to_data(payload: MarketMetadataPayload) -> dict[str, Any]:
    return {
        "accepting_orders": payload.accepting_orders,
        "active": payload.active,
        "archived": payload.archived,
        "closed": payload.closed,
        "closed_at_ms": payload.closed_at_ms,
        "condition_id": payload.condition_id,
        "end_at_ms": payload.end_at_ms,
        "events": [
            {"event_id": event.event_id, "slug": event.slug, "title": event.title}
            for event in payload.events
        ],
        "fee_rate": str(payload.fee_rate),
        "fee_schedule": _fee_schedule_to_data(payload.fee_schedule),
        "fee_type": payload.fee_type,
        "fees_enabled": payload.fees_enabled,
        "market_id": payload.market_id,
        "market_slug": payload.market_slug,
        "minimum_order_size": _optional_decimal(payload.minimum_order_size),
        "minimum_tick_size": _optional_decimal(payload.minimum_tick_size),
        "neg_risk": payload.neg_risk,
        "neg_risk_request_id": payload.neg_risk_request_id,
        "order_book_enabled": payload.order_book_enabled,
        "outcomes": [
            {
                "label": outcome.label,
                "price": _optional_decimal(outcome.price),
                "token_id": outcome.token_id,
            }
            for outcome in payload.outcomes
        ],
        "question": payload.question,
        "question_id": payload.question_id,
        "resolution_source": payload.resolution_source,
        "resolution_status": payload.resolution_status,
        "resolved": payload.resolved,
        "resolved_by": payload.resolved_by,
        "seconds_delay": payload.seconds_delay,
        "start_at_ms": payload.start_at_ms,
        "winning_outcome": payload.winning_outcome,
        "winning_token_id": payload.winning_token_id,
    }


def _fee_schedule_to_data(
    fee_schedule: FeeScheduleMetadata | None,
) -> dict[str, Any] | None:
    if fee_schedule is None:
        return None
    return {
        "exponent": str(fee_schedule.exponent),
        "rate": str(fee_schedule.rate),
        "rebate_rate": str(fee_schedule.rebate_rate),
        "taker_only": fee_schedule.taker_only,
    }


def _baseline_to_data(payload: BookBaselinePayload) -> dict[str, Any]:
    return {
        "asks": [_level_to_data(level) for level in payload.asks],
        "bids": [_level_to_data(level) for level in payload.bids],
        "source_hash": payload.source_hash,
        "token_id": payload.token_id,
    }


def _level_to_data(level: RecordedBookLevel) -> dict[str, str]:
    return {"price": str(level.price), "size": str(level.size)}


def _change_to_data(change: BookChange) -> dict[str, Any]:
    return {
        "best_ask": _optional_decimal(change.best_ask),
        "best_bid": _optional_decimal(change.best_bid),
        "price": str(change.price),
        "side": change.side.value,
        "size": str(change.size),
        "source_hash": change.source_hash,
        "token_id": change.token_id,
    }


def _metadata_from_data(data: dict[str, Any]) -> MarketMetadataPayload:
    _require_keys(data, _MARKET_METADATA_KEYS)
    events_data = _list(data["events"], "market events")
    outcomes_data = _list(data["outcomes"], "market outcomes")
    events = tuple(_event_metadata_from_data(value) for value in events_data)
    outcomes = tuple(_outcome_metadata_from_data(value) for value in outcomes_data)
    if len(outcomes) != 2:
        raise ValueError("recording payload market outcomes must contain two values")
    return MarketMetadataPayload(
        market_id=_text(data["market_id"], "market ID"),
        condition_id=_text(data["condition_id"], "condition ID"),
        market_slug=_text(data["market_slug"], "market slug"),
        question=_text(data["question"], "market question"),
        events=events,
        outcomes=(outcomes[0], outcomes[1]),
        active=_optional_bool(data["active"], "active"),
        closed=_optional_bool(data["closed"], "closed"),
        archived=_optional_bool(data["archived"], "archived"),
        start_at_ms=_optional_int(data["start_at_ms"], "start timestamp"),
        end_at_ms=_optional_int(data["end_at_ms"], "end timestamp"),
        closed_at_ms=_optional_int(data["closed_at_ms"], "closed timestamp"),
        order_book_enabled=_optional_bool(
            data["order_book_enabled"],
            "order-book state",
        ),
        accepting_orders=_optional_bool(
            data["accepting_orders"],
            "accepting-orders state",
        ),
        minimum_tick_size=_optional_decimal_from_data(
            data["minimum_tick_size"],
            "minimum tick size",
        ),
        minimum_order_size=_optional_decimal_from_data(
            data["minimum_order_size"],
            "minimum order size",
        ),
        seconds_delay=_optional_int(data["seconds_delay"], "seconds delay"),
        neg_risk=_optional_bool(data["neg_risk"], "negative-risk state"),
        fees_enabled=_optional_bool(data["fees_enabled"], "fee state"),
        fee_type=_optional_text(data["fee_type"], "fee type"),
        fee_schedule=_fee_schedule_from_data(data["fee_schedule"]),
        fee_rate=_decimal(data["fee_rate"], "fee rate"),
        question_id=_optional_text(data["question_id"], "question ID"),
        neg_risk_request_id=_optional_text(
            data["neg_risk_request_id"],
            "negative-risk request ID",
        ),
        resolution_status=_optional_text(
            data["resolution_status"],
            "resolution status",
        ),
        resolution_source=_optional_text(
            data["resolution_source"],
            "resolution source",
        ),
        resolved_by=_optional_text(data["resolved_by"], "resolver"),
        resolved=_bool(data["resolved"], "resolved state"),
        winning_token_id=_optional_text(
            data["winning_token_id"],
            "winning token ID",
        ),
        winning_outcome=_optional_text(
            data["winning_outcome"],
            "winning outcome",
        ),
    )


def _event_metadata_from_data(value: object) -> MarketEventMetadata:
    data = _object(value, "market event")
    _require_keys(data, _MARKET_EVENT_KEYS)
    return MarketEventMetadata(
        event_id=_text(data["event_id"], "event ID"),
        slug=_optional_text(data["slug"], "event slug"),
        title=_optional_text(data["title"], "event title"),
    )


def _outcome_metadata_from_data(value: object) -> MarketOutcomeMetadata:
    data = _object(value, "market outcome")
    _require_keys(data, _MARKET_OUTCOME_KEYS)
    return MarketOutcomeMetadata(
        label=_text(data["label"], "outcome label"),
        token_id=_text(data["token_id"], "outcome token ID"),
        price=_optional_decimal_from_data(data["price"], "outcome price"),
    )


def _fee_schedule_from_data(value: object) -> FeeScheduleMetadata | None:
    if value is None:
        return None
    data = _object(value, "fee schedule")
    _require_keys(data, _FEE_SCHEDULE_KEYS)
    return FeeScheduleMetadata(
        exponent=_decimal(data["exponent"], "fee exponent"),
        rate=_decimal(data["rate"], "fee rate"),
        taker_only=_bool(data["taker_only"], "taker-only state"),
        rebate_rate=_decimal(data["rebate_rate"], "rebate rate"),
    )


def _baseline_from_data(data: dict[str, Any]) -> BookBaselinePayload:
    _require_keys(data, _BOOK_BASELINE_KEYS)
    return BookBaselinePayload(
        token_id=_text(data["token_id"], "book token ID"),
        bids=tuple(
            _level_from_data(value) for value in _list(data["bids"], "book bids")
        ),
        asks=tuple(
            _level_from_data(value) for value in _list(data["asks"], "book asks")
        ),
        source_hash=_optional_text(data["source_hash"], "book source hash"),
    )


def _level_from_data(value: object) -> RecordedBookLevel:
    data = _object(value, "book level")
    _require_keys(data, _BOOK_LEVEL_KEYS)
    return RecordedBookLevel(
        price=_decimal(data["price"], "book price"),
        size=_decimal(data["size"], "book size"),
    )


def _delta_from_data(data: dict[str, Any]) -> BookDeltaPayload:
    _require_keys(data, _BOOK_DELTA_KEYS)
    return BookDeltaPayload(
        changes=tuple(
            _change_from_data(value)
            for value in _list(data["changes"], "book changes")
        )
    )


def _change_from_data(value: object) -> BookChange:
    data = _object(value, "book change")
    _require_keys(data, _BOOK_CHANGE_KEYS)
    return BookChange(
        token_id=_text(data["token_id"], "book change token ID"),
        side=_side(data["side"]),
        price=_decimal(data["price"], "book change price"),
        size=_decimal(data["size"], "book change size"),
        source_hash=_optional_text(data["source_hash"], "change source hash"),
        best_bid=_optional_decimal_from_data(data["best_bid"], "best bid"),
        best_ask=_optional_decimal_from_data(data["best_ask"], "best ask"),
    )


def _public_trade_from_data(data: dict[str, Any]) -> PublicTradePayload:
    _require_keys(data, _PUBLIC_TRADE_KEYS)
    return PublicTradePayload(
        token_id=_text(data["token_id"], "public trade token ID"),
        price=_decimal(data["price"], "public trade price"),
        size=_decimal(data["size"], "public trade size"),
        side=_side(data["side"]),
        fee_rate_bps=_optional_decimal_from_data(
            data["fee_rate_bps"],
            "public trade fee rate",
        ),
        transaction_hash=_optional_text(
            data["transaction_hash"],
            "transaction hash",
        ),
    )


def _tick_size_change_from_data(data: dict[str, Any]) -> TickSizeChangePayload:
    _require_keys(data, _TICK_SIZE_CHANGE_KEYS)
    return TickSizeChangePayload(
        token_id=_text(data["token_id"], "tick-size token ID"),
        old_tick_size=_optional_decimal_from_data(
            data["old_tick_size"],
            "old tick size",
        ),
        new_tick_size=_decimal(data["new_tick_size"], "new tick size"),
    )


def _resolution_from_data(data: dict[str, Any]) -> ResolutionPayload:
    _require_keys(data, _RESOLUTION_KEYS)
    token_ids = _text_tuple(data["token_ids"], "resolution token IDs")
    if len(token_ids) != 2:
        raise ValueError("recording payload resolution requires two token IDs")
    return ResolutionPayload(
        token_ids=(token_ids[0], token_ids[1]),
        winning_token_id=_text(data["winning_token_id"], "winning token ID"),
        winning_outcome=_text(data["winning_outcome"], "winning outcome"),
        source=_text(data["source"], "resolution source"),
        resolution_id=_optional_text(data["resolution_id"], "resolution ID"),
    )


def _coverage_gap_from_data(data: dict[str, Any]) -> CoverageGapPayload:
    _require_keys(data, _COVERAGE_GAP_KEYS)
    return CoverageGapPayload(
        reason=CoverageGapReason(_text(data["reason"], "coverage gap reason")),
        started_at_ms=_int(data["started_at_ms"], "coverage gap start"),
        ended_at_ms=_optional_int(data["ended_at_ms"], "coverage gap end"),
        affected_condition_ids=_text_tuple(
            data["affected_condition_ids"],
            "affected condition IDs",
        ),
        affected_market_slugs=_text_tuple(
            data["affected_market_slugs"],
            "affected market slugs",
        ),
        affected_token_ids=_text_tuple(
            data["affected_token_ids"],
            "affected token IDs",
        ),
        details=_optional_text(data["details"], "coverage gap details"),
    )


def _capture_anomaly_from_data(data: dict[str, Any]) -> CaptureAnomalyPayload:
    _require_keys(data, _CAPTURE_ANOMALY_KEYS)
    return CaptureAnomalyPayload(
        failure_kind=_capture_failure_kind(data["failure_kind"]),
        expected_fingerprint=_fingerprint_from_data(
            data["expected_fingerprint"],
            "expected revision fingerprint",
        ),
        actual_fingerprint=_fingerprint_from_data(
            data["actual_fingerprint"],
            "actual revision fingerprint",
        ),
        fragments=tuple(
            _capture_fragment_from_data(value)
            for value in _list(data["fragments"], "capture anomaly fragments")
        ),
        book_diagnostics=tuple(
            _book_diagnostics_from_data(value)
            for value in _list(
                data["book_diagnostics"],
                "capture anomaly book diagnostics",
            )
        ),
        dropped_count_before=_int(
            data["dropped_count_before"],
            "capture anomaly initial drop count",
        ),
        dropped_count_after=_int(
            data["dropped_count_after"],
            "capture anomaly final drop count",
        ),
        elapsed_ms=_int(data["elapsed_ms"], "capture anomaly elapsed time"),
        details=_optional_text(data["details"], "capture anomaly details"),
    )


def _capture_failure_kind(value: object) -> CaptureFailureKind:
    if not isinstance(value, str):
        raise ValueError("recording capture anomaly failure kind must be text")
    try:
        return CaptureFailureKind(value)
    except ValueError as error:
        raise ValueError(
            "recording capture anomaly failure kind is invalid"
        ) from error


def _fingerprint_from_data(
    value: object,
    name: str,
) -> RevisionFingerprint | None:
    if value is None:
        return None
    data = _object(value, name)
    _require_keys(data, _REVISION_FINGERPRINT_KEYS)
    source_hashes: list[tuple[str, str]] = []
    for entry in _list(data["source_hashes"], "revision source hashes"):
        hash_data = _object(entry, "revision source hash")
        _require_keys(hash_data, _REVISION_SOURCE_HASH_KEYS)
        source_hashes.append(
            (
                _text(hash_data["token_id"], "revision source hash token ID"),
                _text(hash_data["source_hash"], "revision source hash"),
            )
        )
    return RevisionFingerprint(
        condition_id=_text(data["condition_id"], "revision condition ID"),
        source_timestamp_ms=_int(
            data["source_timestamp_ms"],
            "revision source timestamp",
        ),
        source_hashes=tuple(source_hashes),
    )


def _capture_fragment_from_data(value: object) -> CaptureAnomalyFragment:
    data = _object(value, "capture anomaly fragment")
    _require_keys(data, _CAPTURE_FRAGMENT_KEYS)
    identity_data = _object(data["identity"], "capture anomaly identity")
    _require_keys(identity_data, _MARKET_IDENTITY_KEYS)
    payload_data = _object(data["payload"], "capture anomaly fragment payload")
    try:
        kind = PayloadKind(data["payload_kind"])
    except (TypeError, ValueError) as error:
        raise ValueError(
            "recording capture anomaly fragment payload kind is invalid"
        ) from error
    payload = _CODEC_BY_KIND[kind].decode(payload_data)
    try:
        role = CaptureFragmentRole(data["role"])
    except (TypeError, ValueError) as error:
        raise ValueError(
            "recording capture anomaly fragment role is invalid"
        ) from error
    return CaptureAnomalyFragment(
        role=role,
        source_timestamp_ms=_optional_int(
            data["source_timestamp_ms"],
            "capture fragment source timestamp",
        ),
        identity=MarketIdentity(
            condition_id=_optional_text(
                identity_data["condition_id"],
                "capture fragment condition ID",
            ),
            market_slug=_optional_text(
                identity_data["market_slug"],
                "capture fragment market slug",
            ),
            token_id=_optional_text(
                identity_data["token_id"],
                "capture fragment token ID",
            ),
        ),
        payload=payload,
    )


def _book_diagnostics_from_data(value: object) -> CaptureBookDiagnostics:
    data = _object(value, "capture anomaly book diagnostics")
    _require_keys(data, _CAPTURE_BOOK_DIAGNOSTICS_KEYS)
    return CaptureBookDiagnostics(
        token_id=_text(data["token_id"], "capture diagnostics token ID"),
        projected_best_bid=_optional_decimal_from_data(
            data["projected_best_bid"],
            "projected best bid",
        ),
        projected_best_ask=_optional_decimal_from_data(
            data["projected_best_ask"],
            "projected best ask",
        ),
        advertised_best_bid=_optional_decimal_from_data(
            data["advertised_best_bid"],
            "advertised best bid",
        ),
        advertised_best_ask=_optional_decimal_from_data(
            data["advertised_best_ask"],
            "advertised best ask",
        ),
    )


def _load_object(raw_json: str) -> dict[str, Any]:
    return _object(_load_json(raw_json), "payload")


def _load_json(raw_json: str) -> object:
    if not isinstance(raw_json, str):
        raise ValueError("recording payload JSON must be text")
    try:
        return loads_json(raw_json)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("recording payload JSON is malformed") from error

def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"recording {name} must be an object")
    return value


def _require_keys(data: dict[str, Any], keys: frozenset[str]) -> None:
    actual = frozenset(data)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise ValueError(
            f"recording payload fields are invalid; missing={missing}, extra={extra}"
        )


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"recording {name} must be an array")
    return value


def _text_tuple(value: object, name: str) -> tuple[str, ...]:
    return tuple(_text(item, name) for item in _list(value, name))


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"recording {name} must be non-empty trimmed text")
    return value


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"recording {name} must be a decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"recording {name} is not a decimal") from error
    if not parsed.is_finite():
        raise ValueError(f"recording {name} must be finite")
    return parsed


def _optional_decimal_from_data(value: object, name: str) -> Decimal | None:
    return None if value is None else _decimal(value, name)


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"recording {name} must be an integer")
    return value


def _optional_int(value: object, name: str) -> int | None:
    return None if value is None else _int(value, name)


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"recording {name} must be a boolean")
    return value


def _optional_bool(value: object, name: str) -> bool | None:
    return None if value is None else _bool(value, name)


def _side(value: object) -> Side:
    if not isinstance(value, str):
        raise ValueError("recording side must be text")
    try:
        return Side(value)
    except ValueError as error:
        raise ValueError("recording side is invalid") from error


_MARKET_METADATA_KEYS = frozenset(
    {
        "accepting_orders",
        "active",
        "archived",
        "closed",
        "closed_at_ms",
        "condition_id",
        "end_at_ms",
        "events",
        "fee_rate",
        "fee_schedule",
        "fee_type",
        "fees_enabled",
        "market_id",
        "market_slug",
        "minimum_order_size",
        "minimum_tick_size",
        "neg_risk",
        "neg_risk_request_id",
        "order_book_enabled",
        "outcomes",
        "question",
        "question_id",
        "resolution_source",
        "resolution_status",
        "resolved",
        "resolved_by",
        "seconds_delay",
        "start_at_ms",
        "winning_outcome",
        "winning_token_id",
    }
)
_MARKET_EVENT_KEYS = frozenset({"event_id", "slug", "title"})
_MARKET_OUTCOME_KEYS = frozenset({"label", "price", "token_id"})
_FEE_SCHEDULE_KEYS = frozenset({"exponent", "rate", "rebate_rate", "taker_only"})
_BOOK_BASELINE_KEYS = frozenset({"asks", "bids", "source_hash", "token_id"})
_BOOK_LEVEL_KEYS = frozenset({"price", "size"})
_BOOK_DELTA_KEYS = frozenset({"changes"})
_BOOK_CHANGE_KEYS = frozenset(
    {"best_ask", "best_bid", "price", "side", "size", "source_hash", "token_id"}
)
_PUBLIC_TRADE_KEYS = frozenset(
    {"fee_rate_bps", "price", "side", "size", "token_id", "transaction_hash"}
)
_TICK_SIZE_CHANGE_KEYS = frozenset(
    {"new_tick_size", "old_tick_size", "token_id"}
)
_RESOLUTION_KEYS = frozenset(
    {"resolution_id", "source", "token_ids", "winning_outcome", "winning_token_id"}
)
_COVERAGE_GAP_KEYS = frozenset(
    {
        "affected_condition_ids",
        "affected_market_slugs",
        "affected_token_ids",
        "details",
        "ended_at_ms",
        "reason",
        "started_at_ms",
    }
)
_CAPTURE_ANOMALY_KEYS = frozenset(
    {
        "actual_fingerprint",
        "book_diagnostics",
        "details",
        "dropped_count_after",
        "dropped_count_before",
        "elapsed_ms",
        "expected_fingerprint",
        "failure_kind",
        "fragments",
    }
)
_REVISION_FINGERPRINT_KEYS = frozenset(
    {"condition_id", "source_hashes", "source_timestamp_ms"}
)
_REVISION_SOURCE_HASH_KEYS = frozenset({"source_hash", "token_id"})
_CAPTURE_FRAGMENT_KEYS = frozenset(
    {"identity", "payload", "payload_kind", "role", "source_timestamp_ms"}
)
_MARKET_IDENTITY_KEYS = frozenset({"condition_id", "market_slug", "token_id"})
_CAPTURE_BOOK_DIAGNOSTICS_KEYS = frozenset(
    {
        "advertised_best_ask",
        "advertised_best_bid",
        "projected_best_ask",
        "projected_best_bid",
        "token_id",
    }
)

@dataclass(frozen=True, slots=True)
class PayloadCodec:
    kind: PayloadKind
    payload_type: type
    encode: Callable[[Any], dict[str, Any]]
    decode: Callable[[dict[str, Any]], RecordedPayload]
    token_ids: Callable[[Any], tuple[str, ...]]


def _delta_to_data(payload: BookDeltaPayload) -> dict[str, Any]:
    return {"changes": [_change_to_data(change) for change in payload.changes]}


def _public_trade_to_data(payload: PublicTradePayload) -> dict[str, Any]:
    return {
        "fee_rate_bps": _optional_decimal(payload.fee_rate_bps),
        "price": str(payload.price),
        "side": payload.side.value,
        "size": str(payload.size),
        "token_id": payload.token_id,
        "transaction_hash": payload.transaction_hash,
    }


def _tick_size_change_to_data(payload: TickSizeChangePayload) -> dict[str, Any]:
    return {
        "new_tick_size": str(payload.new_tick_size),
        "old_tick_size": _optional_decimal(payload.old_tick_size),
        "token_id": payload.token_id,
    }


def _resolution_to_data(payload: ResolutionPayload) -> dict[str, Any]:
    return {
        "resolution_id": payload.resolution_id,
        "source": payload.source,
        "token_ids": list(payload.token_ids),
        "winning_outcome": payload.winning_outcome,
        "winning_token_id": payload.winning_token_id,
    }


def _coverage_gap_to_data(payload: CoverageGapPayload) -> dict[str, Any]:
    return {
        "affected_condition_ids": list(payload.affected_condition_ids),
        "affected_market_slugs": list(payload.affected_market_slugs),
        "affected_token_ids": list(payload.affected_token_ids),
        "details": payload.details,
        "ended_at_ms": payload.ended_at_ms,
        "reason": payload.reason.value,
        "started_at_ms": payload.started_at_ms,
    }


def _metadata_tokens(payload: MarketMetadataPayload) -> tuple[str, ...]:
    return tuple(outcome.token_id for outcome in payload.outcomes)


def _delta_tokens(payload: BookDeltaPayload) -> tuple[str, ...]:
    return tuple(dict.fromkeys(change.token_id for change in payload.changes))


def _single_token(payload: Any) -> tuple[str, ...]:
    return (payload.token_id,)


PAYLOAD_CODECS = (
    PayloadCodec(
        PayloadKind.MARKET_METADATA,
        MarketMetadataPayload,
        _metadata_to_data,
        _metadata_from_data,
        _metadata_tokens,
    ),
    PayloadCodec(
        PayloadKind.BOOK_BASELINE,
        BookBaselinePayload,
        _baseline_to_data,
        _baseline_from_data,
        _single_token,
    ),
    PayloadCodec(
        PayloadKind.BOOK_DELTA,
        BookDeltaPayload,
        _delta_to_data,
        _delta_from_data,
        _delta_tokens,
    ),
    PayloadCodec(
        PayloadKind.PUBLIC_TRADE,
        PublicTradePayload,
        _public_trade_to_data,
        _public_trade_from_data,
        _single_token,
    ),
    PayloadCodec(
        PayloadKind.TICK_SIZE_CHANGE,
        TickSizeChangePayload,
        _tick_size_change_to_data,
        _tick_size_change_from_data,
        _single_token,
    ),
    PayloadCodec(
        PayloadKind.RESOLUTION,
        ResolutionPayload,
        _resolution_to_data,
        _resolution_from_data,
        lambda payload: payload.token_ids,
    ),
    PayloadCodec(
        PayloadKind.COVERAGE_GAP,
        CoverageGapPayload,
        _coverage_gap_to_data,
        _coverage_gap_from_data,
        lambda payload: payload.affected_token_ids,
    ),
)
_CODEC_BY_KIND = {codec.kind: codec for codec in PAYLOAD_CODECS}
_CODEC_BY_TYPE = {codec.payload_type: codec for codec in PAYLOAD_CODECS}

if (
    len(_CODEC_BY_KIND) != len(PayloadKind)
    or frozenset(_CODEC_BY_TYPE) != frozenset(RECORDED_PAYLOAD_TYPES)
):
    raise RuntimeError("recording payload codec registry is incomplete")


def _codec_for_payload(payload: RecordedPayload) -> PayloadCodec:
    codec = _CODEC_BY_TYPE.get(type(payload))
    if codec is None:
        raise ValueError("recording payload type is unsupported")
    return codec
