"""Package-owned values emitted by the Polymarket recording adapter."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.recording.contracts.anomalies import RevisionFingerprint
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
    TickSizeChangePayload,
)
from polybot.recording.contracts.market import MarketIdentity
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)

type CapturedMarketPayload = (
    BookBaselinePayload
    | BookDeltaPayload
    | PublicTradePayload
    | TickSizeChangePayload
    | ResolutionPayload
)


@dataclass(frozen=True, slots=True)
class CapturedMarketEvent:
    source_timestamp_ms: int | None
    identity: MarketIdentity
    payload: CapturedMarketPayload

    def delta_revision_fingerprint(
        self,
    ) -> RevisionFingerprint | None:
        payload = self.payload
        condition_id = self.identity.condition_id
        source_timestamp_ms = self.source_timestamp_ms
        if (
            not isinstance(payload, BookDeltaPayload)
            or condition_id is None
            or source_timestamp_ms is None
        ):
            return None
        source_hashes: dict[str, str] = {}
        for change in payload.changes:
            source_hash = change.source_hash
            if source_hash is None:
                return None
            existing = source_hashes.setdefault(change.token_id, source_hash)
            if existing != source_hash:
                return None
        return RevisionFingerprint(
            condition_id=condition_id,
            source_timestamp_ms=source_timestamp_ms,
            source_hashes=tuple(source_hashes.items()),
        )
