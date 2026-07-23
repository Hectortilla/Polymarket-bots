"""Non-book market-event payloads and their shared identity rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias

from polybot.framework.events import Side

from .book import (
    BookBaselinePayload,
    BookDeltaPayload,
    TickSizeChangePayload,
)
from .gaps import CoverageGapPayload
from .market import MarketIdentity, MarketMetadataPayload
from .validation import (
    normalize_optional_text_fields,
    normalize_required_text_fields,
    validate_book_price,
    validate_decimal,
)


@dataclass(frozen=True, slots=True)
class PublicTradePayload:
    token_id: str
    price: Decimal
    size: Decimal
    side: Side
    fee_rate_bps: Decimal | None = None
    transaction_hash: str | None = None

    def __post_init__(self) -> None:
        normalize_required_text_fields(self, ("token_id",))
        normalize_optional_text_fields(self, ("transaction_hash",))
        if not isinstance(self.side, Side):
            raise ValueError("public trade side is invalid")
        validate_book_price(self.price)
        validate_decimal(
            self.size,
            "public trade size",
            minimum=Decimal("0"),
            minimum_inclusive=False,
        )
        if self.fee_rate_bps is not None:
            validate_decimal(
                self.fee_rate_bps,
                "public trade fee rate",
                minimum=Decimal("0"),
            )


@dataclass(frozen=True, slots=True)
class ResolutionPayload:
    token_ids: tuple[str, str]
    winning_token_id: str
    winning_outcome: str
    source: str
    resolution_id: str | None = None

    def __post_init__(self) -> None:
        normalize_required_text_fields(
            self,
            ("winning_token_id", "winning_outcome", "source"),
        )
        normalize_optional_text_fields(self, ("resolution_id",))
        if (
            not isinstance(self.token_ids, tuple)
            or len(self.token_ids) != 2
            or not all(
                isinstance(token_id, str) and token_id.strip()
                for token_id in self.token_ids
            )
        ):
            raise ValueError("market resolution requires two token IDs")
        normalized_token_ids = tuple(token_id.strip() for token_id in self.token_ids)
        object.__setattr__(self, "token_ids", normalized_token_ids)
        if len(set(normalized_token_ids)) != 2:
            raise ValueError("market resolution token IDs must be distinct")
        if self.winning_token_id not in normalized_token_ids:
            raise ValueError("winning token does not belong to the resolved market")


RecordedPayload: TypeAlias = (
    MarketMetadataPayload
    | BookBaselinePayload
    | BookDeltaPayload
    | PublicTradePayload
    | TickSizeChangePayload
    | ResolutionPayload
    | CoverageGapPayload
)

RECORDED_PAYLOAD_TYPES = (
    MarketMetadataPayload,
    BookBaselinePayload,
    BookDeltaPayload,
    PublicTradePayload,
    TickSizeChangePayload,
    ResolutionPayload,
    CoverageGapPayload,
)


def event_token_ids(payload: RecordedPayload) -> tuple[str, ...]:
    if isinstance(payload, MarketMetadataPayload):
        return tuple(outcome.token_id for outcome in payload.outcomes)
    if isinstance(payload, BookBaselinePayload):
        return (payload.token_id,)
    if isinstance(payload, BookDeltaPayload):
        return tuple(dict.fromkeys(change.token_id for change in payload.changes))
    if isinstance(payload, (PublicTradePayload, TickSizeChangePayload)):
        return (payload.token_id,)
    if isinstance(payload, ResolutionPayload):
        return payload.token_ids
    return payload.affected_token_ids


def validate_event_identity(
    identity: MarketIdentity | None,
    payload: RecordedPayload,
) -> None:
    if isinstance(payload, CoverageGapPayload):
        if identity is not None and not isinstance(identity, MarketIdentity):
            raise ValueError("coverage gap market identity is invalid")
        return
    if not isinstance(identity, MarketIdentity):
        raise ValueError("recorded market event requires market identity")
    if isinstance(payload, MarketMetadataPayload):
        if (
            identity.condition_id != payload.condition_id
            or identity.market_slug != payload.market_slug
            or identity.token_id is not None
        ):
            raise ValueError("metadata identity does not match its event")
        return
    if isinstance(payload, BookDeltaPayload):
        token_ids = event_token_ids(payload)
        if identity.token_id is not None and (
            len(token_ids) != 1 or identity.token_id != token_ids[0]
        ):
            raise ValueError("book delta token identity does not match its changes")
        return
    if isinstance(payload, ResolutionPayload):
        if identity.token_id is not None:
            raise ValueError("market resolution identity cannot select one token")
        return
    validate_token_identity(identity, payload.token_id, "recorded event")


def validate_token_identity(
    identity: MarketIdentity,
    token_id: str,
    subject: str,
) -> None:
    if identity.token_id != token_id:
        raise ValueError(f"{subject} token identity does not match its payload")
