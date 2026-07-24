"""Atomic persistence and idempotency checks for resolution settlements."""

from __future__ import annotations

from pathlib import Path

from polybot.async_io import run_blocking
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    MarketSettlementEvent,
)
from polybot.persistence.atomic_json import AtomicJsonFile

from .schema import (
    RESOLUTION_LEDGER_VERSION,
    RESOLUTION_LEDGER_VERSION_FIELD,
    RESOLUTION_RECORDS_FIELD,
)
from .contracts import ResolutionRecord
from .validation import parse_resolution_records


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
        self._records[event.condition_id] = ResolutionRecord(
            winning_token_id=event.winning_token_id,
            winning_outcome=event.winning_outcome,
            resolved_at_ms=event.resolved_at_ms,
            settled_at_ms=settlement.settled_at_ms,
            source=event.source,
        )
        self._file.write(
            {
                RESOLUTION_LEDGER_VERSION_FIELD: RESOLUTION_LEDGER_VERSION,
                RESOLUTION_RECORDS_FIELD: {
                    condition_id: record.to_dict()
                    for condition_id, record in self._records.items()
                },
            }
        )

    def _existing_record(
        self,
        event: MarketResolutionEvent,
    ) -> ResolutionRecord | None:
        existing = self._records.get(event.condition_id)
        if (
            existing is not None
            and existing.winning_token_id != event.winning_token_id
        ):
            raise ValueError("conflicting resolution already persisted")
        return existing
