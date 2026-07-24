"""Official SDK adapter for normalized positions."""

from __future__ import annotations

from collections.abc import AsyncIterable, Sequence
from typing import Protocol

from polymarket import PolymarketError

from polybot.async_io import run_blocking
from polybot.framework.wallets import normalize_wallet_address
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
    MarketDataTransportError,
)
from polybot.polymarket.pagination import sdk_page_items

from .contracts import Position
from .fields import (
    POSITIONS_REQUEST_MARKET_FIELD,
    POSITIONS_REQUEST_PAGE_SIZE_FIELD,
    POSITIONS_REQUEST_SIZE_THRESHOLD_FIELD,
    POSITIONS_REQUEST_USER_FIELD,
)
from .normalization import normalize_position


POSITIONS_PAGE_SIZE = 100


class PositionDataClient(Protocol):
    """Narrow official-client surface consumed by the positions adapter."""

    def list_positions(
        self,
        *,
        user: str,
        size_threshold: int,
        page_size: int,
        market: tuple[str, ...] | None = None,
    ) -> AsyncIterable[object]:
        ...


class PositionClient:
    def __init__(self, client: PositionDataClient) -> None:
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
            POSITIONS_REQUEST_USER_FIELD: requested_wallet,
            POSITIONS_REQUEST_SIZE_THRESHOLD_FIELD: 0,
            POSITIONS_REQUEST_PAGE_SIZE_FIELD: POSITIONS_PAGE_SIZE,
        }
        if condition_ids is not None:
            request[POSITIONS_REQUEST_MARKET_FIELD] = tuple(condition_ids)
        try:
            paginator = await run_blocking(self._client.list_positions, **request)
            positions_by_token: dict[str, Position] = {}
            async for page in paginator:
                for source in sdk_page_items(
                    page,
                    malformed_error=MarketDataError(
                        MarketDataIssue.INVALID_POSITION,
                        "position page items are malformed",
                    ),
                ):
                    position = normalize_position(
                        source,
                        requested_wallet=requested_wallet,
                        requested_conditions=requested_conditions,
                    )
                    previous = positions_by_token.get(position.token_id)
                    if previous is not None:
                        raise MarketDataError(
                            MarketDataIssue.INVALID_POSITION,
                            "position response contains duplicate token ID: "
                            f"{position.token_id}",
                        )
                    positions_by_token[position.token_id] = position
        except PolymarketError as error:
            raise MarketDataTransportError("position lookup failed") from error
        return list(positions_by_token.values())
