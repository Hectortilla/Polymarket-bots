"""SDK-to-recording metadata normalization at the Gamma adapter boundary."""

from __future__ import annotations

from polymarket.models.gamma.market import Market as SdkMarket

from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.normalization.market import normalize_market
from polybot.polymarket.normalization.timestamps import datetime_to_epoch_ms
from polybot.polymarket.normalization.values import (
    _non_negative_decimal,
    _optional_boolean,
    _optional_probability,
    _optional_text,
    _required_text,
)
from polybot.recording.contracts.market import (
    FeeScheduleMetadata,
    MarketEventMetadata,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
)

from .contracts import RecordingMarket


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
        active=_optional_boolean(state.active, "active state"),
        closed=_optional_boolean(state.closed, "closed state"),
        archived=_optional_boolean(state.archived, "archived state"),
        start_at_ms=datetime_to_epoch_ms(state.start_date),
        end_at_ms=datetime_to_epoch_ms(state.end_date),
        closed_at_ms=datetime_to_epoch_ms(state.closed_time),
        order_book_enabled=_optional_boolean(
            state.enable_order_book,
            "order-book state",
        ),
        accepting_orders=_optional_boolean(
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
        fees_enabled=_optional_boolean(trading.fees_enabled, "fee-enabled state"),
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


def _optional_non_negative_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{name} must be a non-negative integer",
        )
    return value
