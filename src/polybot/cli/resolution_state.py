"""Persistence for idempotent market-resolution settlements."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from polybot.async_io import run_blocking
from polybot.framework.events.resolutions import (
    BINARY_OUTCOMES,
    MarketResolutionEvent,
    MarketSettlementEvent,
    RESOLUTION_RESOLVED_AT_MS_FIELD,
    RESOLUTION_SETTLED_AT_MS_FIELD,
    RESOLUTION_SOURCE_FIELD,
    RESOLUTION_WINNING_OUTCOME_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
)

from .persistence import AtomicJsonFile

RESOLUTION_LEDGER_VERSION = 1
RESOLUTION_LEDGER_VERSION_FIELD = "version"
RESOLUTION_RECORDS_FIELD = "resolutions"


class ResolutionLedger:
    def __init__(self, path: Path) -> None:
        self._file = AtomicJsonFile(path)
        self._records = _load_records(self._file.read())

    @classmethod
    async def create(cls, path: Path) -> ResolutionLedger:
        """Load the ledger without performing filesystem I/O on the event loop."""

        ledger = cls.__new__(cls)
        ledger._file = AtomicJsonFile(path)
        payload = await run_blocking(ledger._file.read)
        ledger._records = _load_records(payload)
        return ledger

    def contains(self, event: MarketResolutionEvent) -> bool:
        return self._existing_record(event) is not None

    def record(self, settlement: MarketSettlementEvent) -> None:
        event = settlement.resolution
        if self._existing_record(event) is not None:
            return
        self._records[event.condition_id] = {
            RESOLUTION_WINNING_TOKEN_ID_FIELD: event.winning_token_id,
            RESOLUTION_WINNING_OUTCOME_FIELD: event.winning_outcome,
            RESOLUTION_RESOLVED_AT_MS_FIELD: event.resolved_at_ms,
            RESOLUTION_SETTLED_AT_MS_FIELD: settlement.settled_at_ms,
            RESOLUTION_SOURCE_FIELD: event.source,
        }
        self._file.write(
            {
                RESOLUTION_LEDGER_VERSION_FIELD: RESOLUTION_LEDGER_VERSION,
                RESOLUTION_RECORDS_FIELD: self._records,
            }
        )

    def _existing_record(self, event: MarketResolutionEvent) -> dict[str, Any] | None:
        existing = self._records.get(event.condition_id)
        if (
            existing is not None
            and existing.get(RESOLUTION_WINNING_TOKEN_ID_FIELD)
            != event.winning_token_id
        ):
            raise ValueError("conflicting resolution already persisted")
        return existing


def _load_records(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    version = payload.get(RESOLUTION_LEDGER_VERSION_FIELD)
    if version not in (None, RESOLUTION_LEDGER_VERSION):
        raise ValueError(f"unsupported resolution ledger version: {version}")
    return _validated_records(payload.get(RESOLUTION_RECORDS_FIELD, {}))


def _validated_records(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("resolution ledger must contain an object")
    records: dict[str, dict[str, Any]] = {}
    for condition_id, record in value.items():
        if not isinstance(condition_id, str) or not condition_id:
            raise ValueError("resolution ledger contains an invalid condition ID")
        if not isinstance(record, dict):
            raise ValueError("resolution ledger record must be an object")
        winning_token_id = record.get(RESOLUTION_WINNING_TOKEN_ID_FIELD)
        winning_outcome = record.get(RESOLUTION_WINNING_OUTCOME_FIELD)
        source = record.get(RESOLUTION_SOURCE_FIELD)
        if (
            not isinstance(winning_token_id, str)
            or not winning_token_id
            or winning_outcome not in BINARY_OUTCOMES
            or not isinstance(source, str)
            or not source
        ):
            raise ValueError("resolution ledger record identity is invalid")
        for key in (RESOLUTION_RESOLVED_AT_MS_FIELD, RESOLUTION_SETTLED_AT_MS_FIELD):
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
            RESOLUTION_RESOLVED_AT_MS_FIELD: record[RESOLUTION_RESOLVED_AT_MS_FIELD],
            RESOLUTION_SETTLED_AT_MS_FIELD: record[RESOLUTION_SETTLED_AT_MS_FIELD],
            RESOLUTION_SOURCE_FIELD: source,
        }
    return records
