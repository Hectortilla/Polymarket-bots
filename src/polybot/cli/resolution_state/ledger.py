"""Atomic persistence and idempotency checks for resolution settlements."""

from __future__ import annotations

from pathlib import Path

from polybot.async_io import run_blocking
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    MarketSettlementEvent,
    RESOLUTION_RESOLVED_AT_MS_FIELD,
    RESOLUTION_SETTLED_AT_MS_FIELD,
    RESOLUTION_SOURCE_FIELD,
    RESOLUTION_WINNING_OUTCOME_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
)
from polybot.persistence.atomic_json import AtomicJsonFile

from .schema import (
    RESOLUTION_LEDGER_VERSION,
    RESOLUTION_LEDGER_VERSION_FIELD,
    RESOLUTION_RECORDS_FIELD,
)
from .validation import (
    ResolutionRecord,
    parse_resolution_records,
)


class ResolutionLedger:
    """Durable condition-keyed settlement idempotency ledger."""

    def __init__(self, path: Path) -> None:
        self._file = AtomicJsonFile(path)
        self._records = parse_resolution_records(self._file.read())

    @classmethod
    async def create(cls, path: Path) -> ResolutionLedger:
        """Load the ledger without performing filesystem I/O on the event loop."""

        ledger = cls.__new__(cls)
        ledger._file = AtomicJsonFile(path)
        payload = await run_blocking(ledger._file.read)
        ledger._records = parse_resolution_records(payload)
        return ledger

    def contains(self, event: MarketResolutionEvent) -> bool:
        return self._existing_record(event) is not None

    @property
    def resolved_condition_ids(self) -> frozenset[str]:
        return frozenset(self._records)

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

    def _existing_record(
        self,
        event: MarketResolutionEvent,
    ) -> ResolutionRecord | None:
        existing = self._records.get(event.condition_id)
        if (
            existing is not None
            and existing.get(RESOLUTION_WINNING_TOKEN_ID_FIELD)
            != event.winning_token_id
        ):
            raise ValueError("conflicting resolution already persisted")
        return existing
