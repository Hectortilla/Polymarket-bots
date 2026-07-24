"""Strict decoding of persisted resolution-ledger JSON records."""

from __future__ import annotations

from typing import Any

from .contracts import ResolutionRecord, ResolutionRecords
from .schema import (
    RESOLUTION_LEDGER_FIELDS,
    RESOLUTION_LEDGER_VERSION,
    RESOLUTION_LEDGER_VERSION_FIELD,
    RESOLUTION_RECORDS_FIELD,
)


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
        records[condition_id] = ResolutionRecord.from_dict(record)
    return records
