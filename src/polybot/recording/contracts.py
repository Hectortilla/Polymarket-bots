"""Stable, SDK-independent contracts stored in a market recording."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TypeAlias

from polybot.framework.events import Side


class SessionIntegrityStatus(StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MarketIdentity:
    condition_id: str | None = None
    market_slug: str | None = None
    token_id: str | None = None

    def __post_init__(self) -> None:
        _normalize_optional_text_fields(
            self,
            ("condition_id", "market_slug", "token_id"),
        )
        if self.condition_id is None and self.market_slug is None:
            raise ValueError("market identity requires a condition ID or market slug")


@dataclass(frozen=True, slots=True)
class MarketOutcomeMetadata:
    label: str
    token_id: str
    price: Decimal | None = None

    def __post_init__(self) -> None:
        _normalize_required_text_fields(self, ("label", "token_id"))
        if self.price is not None:
            _validate_decimal(
                self.price,
                "outcome price",
                minimum=Decimal("0"),
                maximum=Decimal("1"),
            )


@dataclass(frozen=True, slots=True)
class MarketEventMetadata:
    event_id: str
    slug: str | None = None
    title: str | None = None

    def __post_init__(self) -> None:
        _normalize_required_text_fields(self, ("event_id",))
        _normalize_optional_text_fields(self, ("slug", "title"))


@dataclass(frozen=True, slots=True)
class FeeScheduleMetadata:
    exponent: Decimal
    rate: Decimal
    taker_only: bool
    rebate_rate: Decimal

    def __post_init__(self) -> None:
        _validate_decimal(self.exponent, "fee exponent", minimum=Decimal("0"))
        _validate_decimal(self.rate, "fee rate", minimum=Decimal("0"))
        _validate_decimal(self.rebate_rate, "fee rebate rate", minimum=Decimal("0"))
        _validate_bool(self.taker_only, "fee taker-only state")


@dataclass(frozen=True, slots=True)
class MarketMetadataPayload:
    market_id: str
    condition_id: str
    market_slug: str
    question: str
    events: tuple[MarketEventMetadata, ...]
    outcomes: tuple[MarketOutcomeMetadata, MarketOutcomeMetadata]
    active: bool | None
    closed: bool | None
    archived: bool | None
    start_at_ms: int | None
    end_at_ms: int | None
    closed_at_ms: int | None
    order_book_enabled: bool | None
    accepting_orders: bool | None
    minimum_tick_size: Decimal | None
    minimum_order_size: Decimal | None
    seconds_delay: int | None
    neg_risk: bool | None
    fees_enabled: bool | None
    fee_type: str | None
    fee_schedule: FeeScheduleMetadata | None
    fee_rate: Decimal
    question_id: str | None
    neg_risk_request_id: str | None
    resolution_status: str | None
    resolution_source: str | None
    resolved_by: str | None
    resolved: bool
    winning_token_id: str | None
    winning_outcome: str | None

    def __post_init__(self) -> None:
        _normalize_required_text_fields(
            self,
            ("market_id", "condition_id", "market_slug", "question"),
        )
        _normalize_optional_text_fields(
            self,
            (
                "fee_type",
                "question_id",
                "neg_risk_request_id",
                "resolution_status",
                "resolution_source",
                "resolved_by",
                "winning_token_id",
                "winning_outcome",
            ),
        )
        if not isinstance(self.events, tuple) or not all(
            isinstance(event, MarketEventMetadata) for event in self.events
        ):
            raise ValueError("market events must be a tuple of event metadata")
        event_ids = tuple(event.event_id for event in self.events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("market metadata contains duplicate event IDs")
        if (
            not isinstance(self.outcomes, tuple)
            or len(self.outcomes) != 2
            or not all(
                isinstance(outcome, MarketOutcomeMetadata)
                for outcome in self.outcomes
            )
        ):
            raise ValueError("market metadata requires exactly two outcomes")
        token_ids = tuple(outcome.token_id for outcome in self.outcomes)
        if len(set(token_ids)) != 2:
            raise ValueError("market outcome token IDs must be distinct")
        for name in (
            "active",
            "closed",
            "archived",
            "order_book_enabled",
            "accepting_orders",
            "neg_risk",
            "fees_enabled",
        ):
            value = getattr(self, name)
            if value is not None:
                _validate_bool(value, name.replace("_", " "))
        _validate_bool(self.resolved, "resolved state")
        for name in ("start_at_ms", "end_at_ms", "closed_at_ms"):
            value = getattr(self, name)
            if value is not None:
                _validate_nonnegative_int(value, name)
        if self.seconds_delay is not None:
            _validate_nonnegative_int(self.seconds_delay, "market seconds delay")
        if self.minimum_tick_size is not None:
            _validate_decimal(
                self.minimum_tick_size,
                "minimum tick size",
                minimum=Decimal("0"),
                maximum=Decimal("1"),
                minimum_inclusive=False,
            )
        if self.minimum_order_size is not None:
            _validate_decimal(
                self.minimum_order_size,
                "minimum order size",
                minimum=Decimal("0"),
                minimum_inclusive=False,
            )
        _validate_decimal(self.fee_rate, "normalized fee rate", minimum=Decimal("0"))
        if self.fee_schedule is not None and not isinstance(
            self.fee_schedule, FeeScheduleMetadata
        ):
            raise ValueError("market fee schedule is invalid")
        if self.resolved:
            if self.winning_token_id not in token_ids or self.winning_outcome is None:
                raise ValueError("resolved market metadata requires a valid winner")
            outcome_by_token = {
                outcome.token_id: outcome.label for outcome in self.outcomes
            }
            if self.winning_outcome != outcome_by_token[self.winning_token_id]:
                raise ValueError(
                    "resolved market outcome does not match its winning token"
                )
        elif self.winning_token_id is not None or self.winning_outcome is not None:
            raise ValueError("unresolved market metadata cannot declare a winner")


@dataclass(frozen=True, slots=True)
class RecordedBookLevel:
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        _validate_book_price(self.price)
        _validate_decimal(
            self.size,
            "book level size",
            minimum=Decimal("0"),
            minimum_inclusive=False,
        )


@dataclass(frozen=True, slots=True)
class BookBaselinePayload:
    token_id: str
    bids: tuple[RecordedBookLevel, ...]
    asks: tuple[RecordedBookLevel, ...]
    source_hash: str | None = None

    def __post_init__(self) -> None:
        _normalize_required_text_fields(self, ("token_id",))
        _normalize_optional_text_fields(self, ("source_hash",))
        for name in ("bids", "asks"):
            levels = getattr(self, name)
            if not isinstance(levels, tuple) or not all(
                isinstance(level, RecordedBookLevel) for level in levels
            ):
                raise ValueError(f"book {name} must be a tuple of book levels")
            prices = tuple(level.price for level in levels)
            if len(prices) != len(set(prices)):
                raise ValueError(f"book {name} contain duplicate price levels")


@dataclass(frozen=True, slots=True)
class BookChange:
    token_id: str
    side: Side
    price: Decimal
    size: Decimal
    source_hash: str | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None

    def __post_init__(self) -> None:
        _normalize_required_text_fields(self, ("token_id",))
        _normalize_optional_text_fields(self, ("source_hash",))
        if not isinstance(self.side, Side):
            raise ValueError("book change side is invalid")
        _validate_book_price(self.price)
        _validate_decimal(self.size, "book change size", minimum=Decimal("0"))
        for name in ("best_bid", "best_ask"):
            value = getattr(self, name)
            if value is not None:
                _validate_decimal(
                    value,
                    name.replace("_", " "),
                    minimum=Decimal("0"),
                    maximum=Decimal("1"),
                )


@dataclass(frozen=True, slots=True)
class BookDeltaPayload:
    changes: tuple[BookChange, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.changes, tuple) or not self.changes or not all(
            isinstance(change, BookChange) for change in self.changes
        ):
            raise ValueError("book delta requires an ordered tuple of changes")


@dataclass(frozen=True, slots=True)
class PublicTradePayload:
    token_id: str
    price: Decimal
    size: Decimal
    side: Side
    fee_rate_bps: Decimal | None = None
    transaction_hash: str | None = None

    def __post_init__(self) -> None:
        _normalize_required_text_fields(self, ("token_id",))
        _normalize_optional_text_fields(self, ("transaction_hash",))
        if not isinstance(self.side, Side):
            raise ValueError("public trade side is invalid")
        _validate_book_price(self.price)
        _validate_decimal(
            self.size,
            "public trade size",
            minimum=Decimal("0"),
            minimum_inclusive=False,
        )
        if self.fee_rate_bps is not None:
            _validate_decimal(
                self.fee_rate_bps,
                "public trade fee rate",
                minimum=Decimal("0"),
            )


@dataclass(frozen=True, slots=True)
class TickSizeChangePayload:
    token_id: str
    old_tick_size: Decimal | None
    new_tick_size: Decimal

    def __post_init__(self) -> None:
        _normalize_required_text_fields(self, ("token_id",))
        if self.old_tick_size is not None:
            _validate_tick_size(self.old_tick_size, "old tick size")
        _validate_tick_size(self.new_tick_size, "new tick size")


@dataclass(frozen=True, slots=True)
class ResolutionPayload:
    token_ids: tuple[str, str]
    winning_token_id: str
    winning_outcome: str
    source: str
    resolution_id: str | None = None

    def __post_init__(self) -> None:
        _normalize_required_text_fields(
            self,
            ("winning_token_id", "winning_outcome", "source"),
        )
        _normalize_optional_text_fields(self, ("resolution_id",))
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


@dataclass(frozen=True, slots=True)
class CoverageGapPayload:
    reason: str
    started_at_ms: int
    ended_at_ms: int | None
    affected_condition_ids: tuple[str, ...] = ()
    affected_market_slugs: tuple[str, ...] = ()
    affected_token_ids: tuple[str, ...] = ()
    details: str | None = None

    def __post_init__(self) -> None:
        _normalize_required_text_fields(self, ("reason",))
        _normalize_optional_text_fields(self, ("details",))
        _validate_nonnegative_int(self.started_at_ms, "coverage gap start")
        if self.ended_at_ms is not None:
            _validate_nonnegative_int(self.ended_at_ms, "coverage gap end")
            if self.ended_at_ms < self.started_at_ms:
                raise ValueError("coverage gap cannot end before it starts")
        for name in (
            "affected_condition_ids",
            "affected_market_slugs",
            "affected_token_ids",
        ):
            normalized = _normalize_text_tuple(getattr(self, name), name)
            object.__setattr__(self, name, normalized)


RecordedPayload: TypeAlias = (
    MarketMetadataPayload
    | BookBaselinePayload
    | BookDeltaPayload
    | PublicTradePayload
    | TickSizeChangePayload
    | ResolutionPayload
    | CoverageGapPayload
)


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    sequence: int
    session_id: int
    subscription_generation: int
    observed_at_ms: int
    source_timestamp_ms: int | None
    identity: MarketIdentity | None
    payload: RecordedPayload

    def __post_init__(self) -> None:
        _validate_positive_int(self.sequence, "recording event sequence")
        _validate_positive_int(self.session_id, "recording session ID")
        _validate_nonnegative_int(
            self.subscription_generation,
            "subscription generation",
        )
        _validate_nonnegative_int(self.observed_at_ms, "event observation timestamp")
        if self.source_timestamp_ms is not None:
            _validate_nonnegative_int(
                self.source_timestamp_ms,
                "event source timestamp",
            )
        if not isinstance(self.payload, _PAYLOAD_TYPES):
            raise ValueError("recording event payload type is unsupported")
        _validate_event_identity(self.identity, self.payload)


@dataclass(frozen=True, slots=True)
class BookCheckpoint:
    sequence: int
    session_id: int
    subscription_generation: int
    observed_at_ms: int
    identity: MarketIdentity
    book: BookBaselinePayload

    def __post_init__(self) -> None:
        _validate_positive_int(self.sequence, "checkpoint sequence")
        _validate_positive_int(self.session_id, "checkpoint session ID")
        _validate_nonnegative_int(
            self.subscription_generation,
            "checkpoint subscription generation",
        )
        _validate_nonnegative_int(
            self.observed_at_ms,
            "checkpoint observation timestamp",
        )
        if not isinstance(self.identity, MarketIdentity):
            raise ValueError("checkpoint market identity is invalid")
        if not isinstance(self.book, BookBaselinePayload):
            raise ValueError("checkpoint book payload is invalid")
        _validate_token_identity(self.identity, self.book.token_id, "checkpoint")


@dataclass(frozen=True, slots=True)
class CoverageGapRecord:
    gap_id: int
    event_sequence: int
    session_id: int
    subscription_generation: int
    observed_at_ms: int
    identity: MarketIdentity | None
    gap: CoverageGapPayload

    def __post_init__(self) -> None:
        _validate_positive_int(self.gap_id, "coverage gap ID")
        _validate_positive_int(self.event_sequence, "coverage gap event sequence")
        _validate_positive_int(self.session_id, "coverage gap session ID")
        _validate_nonnegative_int(
            self.subscription_generation,
            "coverage gap subscription generation",
        )
        _validate_nonnegative_int(self.observed_at_ms, "coverage gap observation")
        if self.identity is not None and not isinstance(self.identity, MarketIdentity):
            raise ValueError("coverage gap identity is invalid")
        if not isinstance(self.gap, CoverageGapPayload):
            raise ValueError("coverage gap payload is invalid")

    @property
    def is_open(self) -> bool:
        return self.gap.ended_at_ms is None


_PAYLOAD_TYPES = (
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


def _validate_event_identity(
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
    _validate_token_identity(identity, payload.token_id, "recorded event")


def _validate_token_identity(
    identity: MarketIdentity,
    token_id: str,
    subject: str,
) -> None:
    if identity.token_id != token_id:
        raise ValueError(f"{subject} token identity does not match its payload")


def _normalize_required_text_fields(instance: object, names: tuple[str, ...]) -> None:
    for name in names:
        value = getattr(instance, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name.replace('_', ' ')} must not be empty")
        object.__setattr__(instance, name, value.strip())


def _normalize_optional_text_fields(instance: object, names: tuple[str, ...]) -> None:
    for name in names:
        value = getattr(instance, name)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name.replace('_', ' ')} must not be empty")
        object.__setattr__(instance, name, value.strip())


def _normalize_text_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name.replace('_', ' ')} must be a tuple")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name.replace('_', ' ')} contains an empty value")
        stripped = item.strip()
        if stripped not in normalized:
            normalized.append(stripped)
    return tuple(normalized)


def _validate_book_price(value: Decimal) -> None:
    _validate_decimal(
        value,
        "book price",
        minimum=Decimal("0"),
        maximum=Decimal("1"),
        minimum_inclusive=False,
    )


def _validate_tick_size(value: Decimal, name: str) -> None:
    _validate_decimal(
        value,
        name,
        minimum=Decimal("0"),
        maximum=Decimal("1"),
        minimum_inclusive=False,
    )


def _validate_decimal(
    value: Decimal,
    name: str,
    *,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    minimum_inclusive: bool = True,
) -> None:
    try:
        is_finite = isinstance(value, Decimal) and value.is_finite()
    except (AttributeError, InvalidOperation):
        is_finite = False
    if not is_finite:
        raise ValueError(f"{name} must be a finite Decimal")
    if minimum is not None:
        below_minimum = value < minimum if minimum_inclusive else value <= minimum
        if below_minimum:
            qualifier = "at least" if minimum_inclusive else "greater than"
            raise ValueError(f"{name} must be {qualifier} {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")


def _validate_positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_nonnegative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _validate_bool(value: bool, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
