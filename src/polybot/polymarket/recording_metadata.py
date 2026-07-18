"""Gamma metadata resolution for historical market recordings."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from polymarket import AsyncPublicClient
from polymarket.models.gamma.market import Market as SdkMarket

from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.normalization.market import normalize_market
from polybot.polymarket.normalization.timestamps import datetime_to_epoch_ms
from polybot.polymarket.types import Market
from polybot.recording.contracts import (
    FeeScheduleMetadata,
    MarketEventMetadata,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
)


@dataclass(frozen=True, slots=True)
class RecordingMarket:
    market: Market
    metadata: MarketMetadataPayload


class RecordingMarketResolver:
    """Resolve replay metadata without returning official SDK models."""

    def __init__(self, client: AsyncPublicClient | None = None) -> None:
        self._gamma = GammaClient(client)

    async def find_by_slug(self, slug: str) -> RecordingMarket | None:
        source = await self._gamma._find_source_by_slug(slug)
        return None if source is None else normalize_recording_market(source)

    async def find_many(
        self,
        slugs: Iterable[str],
    ) -> tuple[RecordingMarket | None, ...]:
        sources = await self._gamma._find_many_sources(slugs)
        return tuple(
            None if source is None else normalize_recording_market(source)
            for source in sources
        )

    async def wait_for_slug(
        self,
        slug: str,
        *,
        retry_delay_s: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> RecordingMarket:
        if retry_delay_s <= 0:
            raise ValueError("retry delay must be positive")
        while True:
            market = await self.find_by_slug(slug)
            if market is not None:
                return market
            await sleep(retry_delay_s)

    async def close(self) -> None:
        await self._gamma.close()


def normalize_recording_market(source: SdkMarket) -> RecordingMarket:
    market = normalize_market(source)
    state = source.state
    trading = source.trading
    resolution = source.resolution
    outcomes = source.outcomes

    events = tuple(
        MarketEventMetadata(
            event_id=_required_text(event.id, "event ID"),
            slug=_optional_text(event.slug, "event slug"),
            title=_optional_text(event.title, "event title"),
        )
        for event in source.events or ()
    )
    outcome_metadata = (
        MarketOutcomeMetadata(
            label=market.outcomes[0].label,
            token_id=market.outcomes[0].token_id,
            price=_optional_probability(outcomes.yes.price, "first outcome price"),
        ),
        MarketOutcomeMetadata(
            label=market.outcomes[1].label,
            token_id=market.outcomes[1].token_id,
            price=_optional_probability(outcomes.no.price, "second outcome price"),
        ),
    )
    fee_schedule = _fee_schedule(trading.fee_schedule)
    resolution_status = None
    if resolution is not None and resolution.uma_resolution_status is not None:
        raw_status = resolution.uma_resolution_status
        resolution_status = _required_text(
            getattr(raw_status, "value", raw_status),
            "resolution status",
        )

    metadata = MarketMetadataPayload(
        market_id=_required_text(source.id, "market ID"),
        condition_id=market.condition_id,
        market_slug=market.slug,
        question=market.question,
        events=events,
        outcomes=outcome_metadata,
        active=_optional_bool(state.active, "active state"),
        closed=_optional_bool(state.closed, "closed state"),
        archived=_optional_bool(state.archived, "archived state"),
        start_at_ms=datetime_to_epoch_ms(state.start_date),
        end_at_ms=datetime_to_epoch_ms(state.end_date),
        closed_at_ms=datetime_to_epoch_ms(state.closed_time),
        order_book_enabled=_optional_bool(
            state.enable_order_book,
            "order-book state",
        ),
        accepting_orders=_optional_bool(
            state.accepting_orders,
            "order-acceptance state",
        ),
        minimum_tick_size=market.minimum_tick_size,
        minimum_order_size=market.minimum_order_size,
        seconds_delay=_optional_non_negative_int(
            trading.seconds_delay,
            "seconds delay",
        ),
        neg_risk=market.neg_risk,
        fees_enabled=_optional_bool(trading.fees_enabled, "fee-enabled state"),
        fee_type=_optional_text(trading.fee_type, "fee type"),
        fee_schedule=fee_schedule,
        fee_rate=market.fee_rate,
        question_id=(
            None
            if resolution is None
            else _optional_text(resolution.question_id, "resolution question ID")
        ),
        neg_risk_request_id=(
            None
            if resolution is None
            else _optional_text(
                resolution.neg_risk_request_id,
                "negative-risk request ID",
            )
        ),
        resolution_status=resolution_status,
        resolution_source=(
            None
            if resolution is None
            else _optional_text(resolution.source, "resolution source")
        ),
        resolved_by=(
            None
            if resolution is None
            else _optional_text(resolution.resolved_by, "resolver address")
        ),
        resolved=market.resolved,
        winning_token_id=market.winning_token_id,
        winning_outcome=market.winning_outcome,
    )
    return RecordingMarket(market=market, metadata=metadata)


def _fee_schedule(source: object) -> FeeScheduleMetadata | None:
    if source is None:
        return None
    try:
        exponent = source.exponent  # type: ignore[attr-defined]
        rate = source.rate  # type: ignore[attr-defined]
        taker_only = source.taker_only  # type: ignore[attr-defined]
        rebate_rate = source.rebate_rate  # type: ignore[attr-defined]
    except AttributeError as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market fee schedule is malformed",
        ) from error
    if not isinstance(taker_only, bool):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market fee schedule taker-only flag is malformed",
        )
    return FeeScheduleMetadata(
        exponent=_non_negative_decimal(exponent, "fee exponent"),
        rate=_non_negative_decimal(rate, "fee rate"),
        taker_only=taker_only,
        rebate_rate=_non_negative_decimal(rebate_rate, "fee rebate rate"),
    )


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{name} is missing",
        )
    return value.strip()


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else _required_text(value, name)


def _optional_bool(value: object, name: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise MarketDataError(
        MarketDataIssue.INVALID_MARKET_PARAMETERS,
        f"{name} is malformed",
    )


def _optional_non_negative_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{name} must be a non-negative integer",
        )
    return value


def _optional_probability(value: object, name: str) -> Decimal | None:
    if value is None:
        return None
    normalized = _decimal(value, name)
    if not Decimal("0") <= normalized <= Decimal("1"):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{name} must be between zero and one",
        )
    return normalized


def _non_negative_decimal(value: object, name: str) -> Decimal:
    normalized = _decimal(value, name)
    if normalized < 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{name} must not be negative",
        )
    return normalized


def _decimal(value: object, name: str) -> Decimal:
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{name} is malformed",
        ) from error
    if not normalized.is_finite():
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{name} must be finite",
        )
    return normalized
