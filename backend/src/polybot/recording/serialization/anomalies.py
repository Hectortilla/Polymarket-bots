"""Structured codecs for capture-anomaly payloads."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..contracts.anomalies import (
    CaptureAnomalyFragment,
    CaptureAnomalyPayload,
    CaptureBookDiagnostics,
    CaptureFailureKind,
    CaptureFragmentRole,
    RevisionFingerprint,
)
from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketIdentity
from . import fields
from .parsing import (
    decimal_to_json,
    optional_decimal_from_json,
    optional_integer,
    optional_text,
    require_array,
    require_exact_keys,
    require_integer,
    require_object,
    require_text,
)
from .registry import decode_payload_data, encode_payload, payload_kind


def encode_capture_anomaly(anomaly: CaptureAnomalyPayload) -> dict[str, Any]:
    return {
        fields.ACTUAL_FINGERPRINT_FIELD: _fingerprint_to_data(
            anomaly.actual_fingerprint
        ),
        fields.BOOK_DIAGNOSTICS_FIELD: [
            _book_diagnostics_to_data(diagnostics)
            for diagnostics in anomaly.book_diagnostics
        ],
        fields.DETAILS_FIELD: anomaly.details,
        fields.DROPPED_COUNT_AFTER_FIELD: anomaly.dropped_count_after,
        fields.DROPPED_COUNT_BEFORE_FIELD: anomaly.dropped_count_before,
        fields.ELAPSED_MS_FIELD: anomaly.elapsed_ms,
        fields.EXPECTED_FINGERPRINT_FIELD: _fingerprint_to_data(
            anomaly.expected_fingerprint
        ),
        fields.FAILURE_KIND_FIELD: anomaly.failure_kind.value,
        fields.FRAGMENTS_FIELD: [
            _capture_fragment_to_data(fragment) for fragment in anomaly.fragments
        ],
    }


def _fingerprint_to_data(
    fingerprint: RevisionFingerprint | None,
) -> dict[str, Any] | None:
    if fingerprint is None:
        return None
    return {
        fields.CONDITION_ID_FIELD: fingerprint.condition_id,
        fields.SOURCE_HASHES_FIELD: [
            {
                fields.SOURCE_HASH_FIELD: source_hash,
                fields.TOKEN_ID_FIELD: token_id,
            }
            for token_id, source_hash in fingerprint.source_hashes
        ],
        fields.SOURCE_TIMESTAMP_MS_FIELD: fingerprint.source_timestamp_ms,
    }


def _capture_fragment_to_data(
    fragment: CaptureAnomalyFragment,
) -> dict[str, Any]:
    return {
        fields.IDENTITY_FIELD: _identity_to_data(fragment.identity),
        fields.PAYLOAD_FIELD: encode_payload(fragment.payload),
        fields.PAYLOAD_KIND_FIELD: payload_kind(fragment.payload).value,
        fields.ROLE_FIELD: fragment.role.value,
        fields.SOURCE_TIMESTAMP_MS_FIELD: fragment.source_timestamp_ms,
    }


def _identity_to_data(identity: MarketIdentity) -> dict[str, str | None]:
    return {
        fields.CONDITION_ID_FIELD: identity.condition_id,
        fields.MARKET_SLUG_FIELD: identity.market_slug,
        fields.TOKEN_ID_FIELD: identity.token_id,
    }


def _book_diagnostics_to_data(
    diagnostics: CaptureBookDiagnostics,
) -> dict[str, str | None]:
    return {
        fields.ADVERTISED_BEST_ASK_FIELD: decimal_to_json(
            diagnostics.advertised_best_ask
        ),
        fields.ADVERTISED_BEST_BID_FIELD: decimal_to_json(
            diagnostics.advertised_best_bid
        ),
        fields.PROJECTED_BEST_ASK_FIELD: decimal_to_json(
            diagnostics.projected_best_ask
        ),
        fields.PROJECTED_BEST_BID_FIELD: decimal_to_json(
            diagnostics.projected_best_bid
        ),
        fields.TOKEN_ID_FIELD: diagnostics.token_id,
    }


def decode_capture_anomaly(data: dict[str, Any]) -> CaptureAnomalyPayload:
    require_exact_keys(data, fields.CAPTURE_ANOMALY_FIELDS)
    return CaptureAnomalyPayload(
        failure_kind=_capture_failure_kind(data[fields.FAILURE_KIND_FIELD]),
        expected_fingerprint=_fingerprint_from_data(
            data[fields.EXPECTED_FINGERPRINT_FIELD],
            "expected revision fingerprint",
        ),
        actual_fingerprint=_fingerprint_from_data(
            data[fields.ACTUAL_FINGERPRINT_FIELD],
            "actual revision fingerprint",
        ),
        fragments=tuple(
            _capture_fragment_from_data(value)
            for value in require_array(
                data[fields.FRAGMENTS_FIELD],
                "capture anomaly fragments",
            )
        ),
        book_diagnostics=tuple(
            _book_diagnostics_from_data(value)
            for value in require_array(
                data[fields.BOOK_DIAGNOSTICS_FIELD],
                "capture anomaly book diagnostics",
            )
        ),
        dropped_count_before=require_integer(
            data[fields.DROPPED_COUNT_BEFORE_FIELD],
            "capture anomaly initial drop count",
        ),
        dropped_count_after=require_integer(
            data[fields.DROPPED_COUNT_AFTER_FIELD],
            "capture anomaly final drop count",
        ),
        elapsed_ms=require_integer(
            data[fields.ELAPSED_MS_FIELD],
            "capture anomaly elapsed time",
        ),
        details=optional_text(data[fields.DETAILS_FIELD], "capture anomaly details"),
    )


def _capture_failure_kind(value: object) -> CaptureFailureKind:
    if not isinstance(value, str):
        raise ValueError("recording capture anomaly failure kind must be text")
    try:
        return CaptureFailureKind(value)
    except ValueError as error:
        raise ValueError("recording capture anomaly failure kind is invalid") from error


def _fingerprint_from_data(
    value: object,
    name: str,
) -> RevisionFingerprint | None:
    if value is None:
        return None
    data = require_object(value, name)
    require_exact_keys(data, fields.REVISION_FINGERPRINT_FIELDS)
    source_hashes: list[tuple[str, str]] = []
    for entry in require_array(
        data[fields.SOURCE_HASHES_FIELD],
        "revision source hashes",
    ):
        hash_data = require_object(entry, "revision source hash")
        require_exact_keys(hash_data, fields.REVISION_SOURCE_HASH_FIELDS)
        source_hashes.append(
            (
                require_text(
                    hash_data[fields.TOKEN_ID_FIELD],
                    "revision source hash token ID",
                ),
                require_text(
                    hash_data[fields.SOURCE_HASH_FIELD],
                    "revision source hash",
                ),
            )
        )
    return RevisionFingerprint(
        condition_id=require_text(
            data[fields.CONDITION_ID_FIELD],
            "revision condition ID",
        ),
        source_timestamp_ms=require_integer(
            data[fields.SOURCE_TIMESTAMP_MS_FIELD],
            "revision source timestamp",
        ),
        source_hashes=tuple(source_hashes),
    )


def _capture_fragment_from_data(value: object) -> CaptureAnomalyFragment:
    data = require_object(value, "capture anomaly fragment")
    require_exact_keys(data, fields.CAPTURE_FRAGMENT_FIELDS)
    identity_data = require_object(
        data[fields.IDENTITY_FIELD],
        "capture anomaly identity",
    )
    require_exact_keys(identity_data, fields.MARKET_IDENTITY_FIELDS)
    payload_data = require_object(
        data[fields.PAYLOAD_FIELD],
        "capture anomaly fragment payload",
    )
    try:
        kind = PayloadKind(data[fields.PAYLOAD_KIND_FIELD])
    except (TypeError, ValueError) as error:
        raise ValueError(
            "recording capture anomaly fragment payload kind is invalid"
        ) from error
    payload = decode_payload_data(kind, payload_data)
    try:
        role = CaptureFragmentRole(data[fields.ROLE_FIELD])
    except (TypeError, ValueError) as error:
        raise ValueError(
            "recording capture anomaly fragment role is invalid"
        ) from error
    return CaptureAnomalyFragment(
        role=role,
        source_timestamp_ms=optional_integer(
            data[fields.SOURCE_TIMESTAMP_MS_FIELD],
            "capture fragment source timestamp",
        ),
        identity=MarketIdentity(
            condition_id=optional_text(
                identity_data[fields.CONDITION_ID_FIELD],
                "capture fragment condition ID",
            ),
            market_slug=optional_text(
                identity_data[fields.MARKET_SLUG_FIELD],
                "capture fragment market slug",
            ),
            token_id=optional_text(
                identity_data[fields.TOKEN_ID_FIELD],
                "capture fragment token ID",
            ),
        ),
        payload=payload,
    )


def _book_diagnostics_from_data(value: object) -> CaptureBookDiagnostics:
    data = require_object(value, "capture anomaly book diagnostics")
    require_exact_keys(data, fields.CAPTURE_BOOK_DIAGNOSTICS_FIELDS)
    return CaptureBookDiagnostics(
        token_id=require_text(
            data[fields.TOKEN_ID_FIELD],
            "capture diagnostics token ID",
        ),
        projected_best_bid=optional_decimal_from_json(
            data[fields.PROJECTED_BEST_BID_FIELD],
            "projected best bid",
        ),
        projected_best_ask=optional_decimal_from_json(
            data[fields.PROJECTED_BEST_ASK_FIELD],
            "projected best ask",
        ),
        advertised_best_bid=optional_decimal_from_json(
            data[fields.ADVERTISED_BEST_BID_FIELD],
            "advertised best bid",
        ),
        advertised_best_ask=optional_decimal_from_json(
            data[fields.ADVERTISED_BEST_ASK_FIELD],
            "advertised best ask",
        ),
    )
