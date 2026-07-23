"""Market identity and metadata persisted in recordings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.events.prices import (
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
)

from .validation import (
    normalize_optional_text_fields,
    normalize_required_text_fields,
    validate_bool,
    validate_decimal,
    validate_nonnegative_int,
)


@dataclass(frozen=True, slots=True)
class MarketIdentity:
    condition_id: str | None = None
    market_slug: str | None = None
    token_id: str | None = None

    def __post_init__(self) -> None:
        normalize_optional_text_fields(
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
        normalize_required_text_fields(self, ("label", "token_id"))
        if self.price is not None:
            validate_decimal(
                self.price,
                "outcome price",
                minimum=OUTCOME_PRICE_FLOOR,
                maximum=OUTCOME_PRICE_CEILING,
            )


@dataclass(frozen=True, slots=True)
class MarketEventMetadata:
    event_id: str
    slug: str | None = None
    title: str | None = None

    def __post_init__(self) -> None:
        normalize_required_text_fields(self, ("event_id",))
        normalize_optional_text_fields(self, ("slug", "title"))


@dataclass(frozen=True, slots=True)
class FeeScheduleMetadata:
    exponent: Decimal
    rate: Decimal
    taker_only: bool
    rebate_rate: Decimal

    def __post_init__(self) -> None:
        validate_decimal(self.exponent, "fee exponent", minimum=Decimal("0"))
        validate_decimal(self.rate, "fee rate", minimum=Decimal("0"))
        validate_decimal(self.rebate_rate, "fee rebate rate", minimum=Decimal("0"))
        validate_bool(self.taker_only, "fee taker-only state")


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
        normalize_required_text_fields(
            self,
            ("market_id", "condition_id", "market_slug", "question"),
        )
        normalize_optional_text_fields(
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
                isinstance(outcome, MarketOutcomeMetadata) for outcome in self.outcomes
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
                validate_bool(value, name.replace("_", " "))
        validate_bool(self.resolved, "resolved state")
        for name in ("start_at_ms", "end_at_ms", "closed_at_ms"):
            value = getattr(self, name)
            if value is not None:
                validate_nonnegative_int(value, name)
        if self.seconds_delay is not None:
            validate_nonnegative_int(self.seconds_delay, "market seconds delay")
        if self.minimum_tick_size is not None:
            validate_decimal(
                self.minimum_tick_size,
                "minimum tick size",
                minimum=OUTCOME_PRICE_FLOOR,
                maximum=OUTCOME_PRICE_CEILING,
                minimum_inclusive=False,
            )
        if self.minimum_order_size is not None:
            validate_decimal(
                self.minimum_order_size,
                "minimum order size",
                minimum=Decimal("0"),
                minimum_inclusive=False,
            )
        validate_decimal(self.fee_rate, "normalized fee rate", minimum=Decimal("0"))
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
