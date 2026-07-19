"""Normalized positions and the official-SDK positions adapter."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from polybot.async_io import run_blocking
from polybot.framework.wallets import normalize_wallet_address
from polybot.polymarket.errors import MarketDataError, MarketDataIssue


POSITIONS_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class Position:
    token_id: str
    size: Decimal
    average_price: Decimal | None = None
    condition_id: str | None = None
    market_slug: str | None = None
    outcome: str | None = None
    current_price: Decimal | None = None


class PositionClient:
    def __init__(self, client: object) -> None:
        self._client = client

    async def positions(
        self,
        wallet: str,
        *,
        condition_ids: Sequence[str] | None = None,
    ) -> list[Position]:
        if condition_ids is not None and not condition_ids:
            return []
        requested_wallet = normalize_wallet_address(wallet)
        requested_conditions = None if condition_ids is None else frozenset(condition_ids)
        request: dict[str, object] = {
            "user": requested_wallet,
            "size_threshold": 0,
            "page_size": POSITIONS_PAGE_SIZE,
        }
        if condition_ids is not None:
            request["market"] = tuple(condition_ids)
        paginator = await run_blocking(self._client.list_positions, **request)
        positions_by_token: dict[str, Position] = {}
        async for page in paginator:
            for source in _page_items(page):
                position = _normalize_position(
                    source,
                    requested_wallet=requested_wallet,
                    requested_conditions=requested_conditions,
                )
                previous = positions_by_token.get(position.token_id)
                if previous is not None:
                    raise MarketDataError(
                        MarketDataIssue.INVALID_POSITION,
                        f"position response contains duplicate token ID: {position.token_id}",
                    )
                positions_by_token[position.token_id] = position
        return list(positions_by_token.values())


def _normalize_position(
    source: object,
    *,
    requested_wallet: str,
    requested_conditions: frozenset[str] | None,
) -> Position:
    response_wallet = _required_identifier(getattr(source, "wallet", None))
    token_id = _required_identifier(getattr(source, "token_id", None))
    condition_id = _required_identifier(getattr(source, "condition_id", None))
    market_slug = _required_identifier(getattr(source, "slug", None))
    size = getattr(source, "size", None)
    average_price = getattr(source, "avg_price", None)
    current_price = getattr(source, "cur_price", None)
    raw_outcome = getattr(source, "outcome", None)
    outcome = _optional_text(raw_outcome)
    try:
        normalized_size = Decimal(str(size))
        normalized_average = (
            None if average_price is None else Decimal(str(average_price))
        )
        normalized_current = (
            None if current_price is None else Decimal(str(current_price))
        )
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION, "position values are invalid"
        ) from error
    if (
        response_wallet is None
        or normalize_wallet_address(response_wallet) != requested_wallet
        or token_id is None
        or condition_id is None
        or market_slug is None
        or (requested_conditions is not None and condition_id not in requested_conditions)
        or (raw_outcome is not None and outcome is None)
        or not normalized_size.is_finite()
        or normalized_size <= 0
        or (
            normalized_average is not None
            and (
                not normalized_average.is_finite()
                or not Decimal("0") <= normalized_average <= Decimal("1")
            )
        )
        or (
            normalized_current is not None
            and (
                not normalized_current.is_finite()
                or not Decimal("0") <= normalized_current <= Decimal("1")
            )
        )
    ):
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION,
            "position identity, response scope, or values are incomplete",
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
    return _required_identifier(value)


def _page_items(page: object) -> tuple[object, ...]:
    items = getattr(page, "items", None)
    if not isinstance(items, (list, tuple)):
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION,
            "position page items are malformed",
        )
    return tuple(items)
