"""Strict decoding of persisted resolution-ledger JSON records."""

from __future__ import annotations

from typing import Any, TypeAlias

from polybot.framework.events.resolutions import (
    RESOLUTION_RESOLVED_AT_MS_FIELD,
    RESOLUTION_SETTLED_AT_MS_FIELD,
    RESOLUTION_SOURCE_FIELD,
    RESOLUTION_WINNING_OUTCOME_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
)

from .schema import (
    RESOLUTION_LEDGER_FIELDS,
    RESOLUTION_LEDGER_VERSION,
    RESOLUTION_LEDGER_VERSION_FIELD,
    RESOLUTION_RECORD_FIELDS,
    RESOLUTION_RECORDS_FIELD,
)


ResolutionRecord: TypeAlias = dict[str, Any]
ResolutionRecords: TypeAlias = dict[str, ResolutionRecord]


def parse_resolution_records(payload: dict[str, Any]) -> ResolutionRecords:
    """Validate a whole ledger payload and return its normalized records."""

    if not payload:
        return {}
    version = payload.get(RESOLUTION_LEDGER_VERSION_FIELD)
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != RESOLUTION_LEDGER_VERSION
    ):
        raise ValueError(f"unsupported resolution ledger version: {version}")
    if frozenset(payload) != RESOLUTION_LEDGER_FIELDS:
        raise ValueError("resolution ledger schema is malformed")
    return validate_resolution_records(payload[RESOLUTION_RECORDS_FIELD])


def validate_resolution_records(value: object) -> ResolutionRecords:
    """Validate and copy condition-keyed settlement records."""

    if not isinstance(value, dict):
        raise ValueError("resolution ledger must contain an object")
    records: ResolutionRecords = {}
    for condition_id, record in value.items():
        if not isinstance(condition_id, str) or not condition_id:
            raise ValueError("resolution ledger contains an invalid condition ID")
        if not isinstance(record, dict):
            raise ValueError("resolution ledger record must be an object")
        if frozenset(record) != RESOLUTION_RECORD_FIELDS:
            raise ValueError("resolution ledger record fields are malformed")
        winning_token_id = record.get(RESOLUTION_WINNING_TOKEN_ID_FIELD)
        winning_outcome = record.get(RESOLUTION_WINNING_OUTCOME_FIELD)
        source = record.get(RESOLUTION_SOURCE_FIELD)
        if (
            not isinstance(winning_token_id, str)
            or not winning_token_id
            or not isinstance(winning_outcome, str)
            or not winning_outcome.strip()
            or not isinstance(source, str)
            or not source
        ):
            raise ValueError("resolution ledger record identity is invalid")
        for key in (
            RESOLUTION_RESOLVED_AT_MS_FIELD,
            RESOLUTION_SETTLED_AT_MS_FIELD,
        ):
            timestamp = record.get(key)
            if (
                not isinstance(timestamp, int)
                or isinstance(timestamp, bool)
                or timestamp < 0
            ):
                raise ValueError(f"resolution ledger {key} is invalid")
        records[condition_id] = {
            RESOLUTION_WINNING_TOKEN_ID_FIELD: winning_token_id,
            RESOLUTION_WINNING_OUTCOME_FIELD: winning_outcome,
            RESOLUTION_RESOLVED_AT_MS_FIELD: record[
                RESOLUTION_RESOLVED_AT_MS_FIELD
            ],
            RESOLUTION_SETTLED_AT_MS_FIELD: record[
                RESOLUTION_SETTLED_AT_MS_FIELD
            ],
            RESOLUTION_SOURCE_FIELD: source,
        }
    return records
