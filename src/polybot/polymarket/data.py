from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.async_io import run_blocking
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.types import Position

POSITIONS_PAGE_SIZE = 100


class DataClient:
    def __init__(self, client: object) -> None:
        self._client = client

    async def positions(self, wallet: str) -> list[Position]:
        paginator = await run_blocking(
            self._client.list_positions,
            user=wallet,
            size_threshold=0,
            page_size=POSITIONS_PAGE_SIZE,
        )
        positions: list[Position] = []
        async for page in paginator:
            for source in _page_items(page):
                positions.append(_normalize_position(source))
        return positions


def _normalize_position(source: object) -> Position:
    token_id = _required_identifier(getattr(source, "token_id", None))
    condition_id = _required_identifier(getattr(source, "condition_id", None))
    market_slug = _required_identifier(getattr(source, "slug", None))
    size = getattr(source, "size", None)
    average_price = getattr(source, "avg_price", None)
    current_price = getattr(source, "cur_price", None)
    raw_outcome = getattr(source, "outcome", None)
    outcome = _optional_text(raw_outcome)
    try:
        normalized_size = Decimal(size)
        normalized_average = None if average_price is None else Decimal(average_price)
        normalized_current = None if current_price is None else Decimal(current_price)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION, "position values are invalid"
        ) from error
    if (
        token_id is None
        or condition_id is None
        or market_slug is None
        or (raw_outcome is not None and outcome is None)
        or not normalized_size.is_finite()
        or normalized_size <= 0
        or (normalized_average is not None and not normalized_average.is_finite())
        or (normalized_current is not None and not normalized_current.is_finite())
    ):
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION,
            "position identity or values are incomplete",
        )
    return Position(
        token_id=token_id,
        size=normalized_size,
        average_price=normalized_average,
        condition_id=condition_id,
        market_slug=market_slug,
        outcome=outcome,
        current_price=normalized_current,
    )


def _required_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _page_items(page: object) -> tuple[object, ...]:
    items = getattr(page, "items", None)
    if not isinstance(items, (list, tuple)):
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION,
            "position page items are malformed",
        )
    return tuple(items)
