from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable, Iterable
from typing import Final

from polymarket import PolymarketError

from polybot.framework.clock import system_now_ms
from polybot.framework.events.wallet_trades import WalletTradeEvent, WalletTradeKind
from polybot.framework.wallets import normalize_wallet_address
from polybot.polymarket.pagination import sdk_page_items

from .contracts import (
    WalletActivityIssue,
    WalletDataClient,
    WalletActivityError,
    WalletReadFailure,
    WalletTradeBatch,
    WalletTradeSelector,
)
from .fields import TRADE_ACTIVITY_TYPE
from .normalization import normalize_wallet_trade, sort_key

DATA_TRADES_PAGE_SIZE: Final = 499
DEFAULT_WALLET_TRADE_LIMIT: Final = 100
DEFAULT_MAX_CONCURRENCY: Final = 4


class PolymarketWalletActivityClient:
    """Official-SDK-backed Data API reads for wallet bootstrap/reconciliation."""

    def __init__(
        self,
        client: WalletDataClient,
        *,
        now_ms: Callable[[], int] = system_now_ms,
    ) -> None:
        self._client = client
        self._now_ms = now_ms

    async def latest_trades(
        self,
        wallet: str,
        limit: int = DEFAULT_WALLET_TRADE_LIMIT,
    ) -> tuple[WalletTradeEvent, ...]:
        _require_positive_limit(limit)
        return await self._latest_trades_for_normalized_wallet(
            normalize_wallet_address(wallet),
            limit,
        )

    async def _latest_trades_for_normalized_wallet(
        self,
        wallet: str,
        limit: int,
    ) -> tuple[WalletTradeEvent, ...]:
        try:
            try:
                paginator = self._client.list_trades(
                    user=wallet, taker_only=False, page_size=limit
                )
            except TypeError:
                paginator = self._client.list_trades(user=wallet, page_size=limit)
            return await self._collect_trades(
                paginator,
                limit=limit,
                kind=WalletTradeKind.BACKFILL,
                wallet=wallet,
            )
        except PolymarketError as error:
            raise _wallet_read_error() from error

    async def latest_selector(
        self,
        selector: WalletTradeSelector,
        *,
        start_epoch_seconds: int | None = None,
        end_epoch_seconds: int | None = None,
        limit: int = DATA_TRADES_PAGE_SIZE,
    ) -> tuple[WalletTradeEvent, ...]:
        _require_positive_limit(limit)
        try:
            paginator = self._client.list_trades(
                user=selector.wallet,
                market=selector.condition_ids or None,
                taker_only=False,
                start=start_epoch_seconds,
                end=end_epoch_seconds,
                page_size=limit,
            )
            rows: list[WalletTradeEvent] = []
            async for page in paginator:
                for source in _page_items(page):
                    trade = normalize_wallet_trade(
                        source,
                        observed_at_ms=self._now_ms(),
                        kind=WalletTradeKind.RECONCILIATION,
                    )
                    if trade is None:
                        continue
                    self._validate_trade_scope(trade, selector)
                    rows.append(trade)
                    if len(rows) >= limit:
                        unique = {trade.source_key: trade for trade in rows}
                        return tuple(sorted(unique.values(), key=sort_key))
            unique = {trade.source_key: trade for trade in rows}
            return tuple(sorted(unique.values(), key=sort_key))
        except PolymarketError as error:
            raise _wallet_read_error() from error

    async def latest_activity(
        self,
        wallet: str,
        limit: int = DEFAULT_WALLET_TRADE_LIMIT,
    ) -> tuple[WalletTradeEvent, ...]:
        _require_positive_limit(limit)
        address = normalize_wallet_address(wallet)
        try:
            paginator = self._client.list_activity(
                user=address,
                activity_types=(TRADE_ACTIVITY_TYPE,),
                page_size=limit,
            )
            return await self._collect_trades(
                paginator,
                limit=limit,
                kind=WalletTradeKind.RECONCILIATION,
                wallet=address,
            )
        except PolymarketError as error:
            raise _wallet_read_error() from error

    async def latest_trades_many(
        self,
        wallets: Iterable[str],
        *,
        limit: int = DEFAULT_WALLET_TRADE_LIMIT,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> WalletTradeBatch:
        addresses = tuple(
            dict.fromkeys(normalize_wallet_address(wallet) for wallet in wallets)
        )
        _require_positive_limit(limit)
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        semaphore = asyncio.Semaphore(max_concurrency)

        async def read_wallet_trades(
            wallet: str,
        ) -> tuple[str, tuple[WalletTradeEvent, ...] | None]:
            async with semaphore:
                try:
                    return wallet, await self._latest_trades_for_normalized_wallet(
                        wallet,
                        limit,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return wallet, None

        results = await asyncio.gather(
            *(read_wallet_trades(wallet) for wallet in addresses)
        )
        return _merge_wallet_results(tuple(results))

    async def _collect_trades(
        self,
        paginator: AsyncIterable[object],
        *,
        limit: int,
        kind: WalletTradeKind,
        wallet: str,
    ) -> tuple[WalletTradeEvent, ...]:
        rows: list[WalletTradeEvent] = []
        async for page in paginator:
            for source in _page_items(page):
                trade = normalize_wallet_trade(
                    source,
                    observed_at_ms=self._now_ms(),
                    kind=kind,
                )
                if trade is not None:
                    if trade.wallet != wallet:
                        raise WalletActivityError(
                            WalletActivityIssue.WALLET_READ_FAILED,
                            "wallet activity response did not match the requested wallet",
                        )
                    rows.append(trade)
                if len(rows) >= limit:
                    return tuple(sorted(rows, key=sort_key))
        return tuple(sorted(rows, key=sort_key))

    @staticmethod
    def _validate_trade_scope(
        trade: WalletTradeEvent,
        selector: WalletTradeSelector,
    ) -> None:
        if selector.accepts(trade):
            return
        detail = (
            "wallet activity response did not match the requested wallet"
            if selector.wallet is not None and trade.wallet != selector.wallet
            else "wallet activity response did not match the requested market"
        )
        raise WalletActivityError(WalletActivityIssue.WALLET_READ_FAILED, detail)


def _merge_wallet_results(
    results: tuple[tuple[str, tuple[WalletTradeEvent, ...] | None], ...],
) -> WalletTradeBatch:
    failures = tuple(
        WalletReadFailure(wallet, WalletActivityIssue.WALLET_READ_FAILED)
        for wallet, wallet_trades in results
        if wallet_trades is None
    )
    unique = {
        trade.source_key: trade
        for _, wallet_trades in results
        if wallet_trades
        for trade in wallet_trades
    }
    return WalletTradeBatch(tuple(sorted(unique.values(), key=sort_key)), failures)


def _wallet_read_error() -> WalletActivityError:
    return WalletActivityError(
        WalletActivityIssue.WALLET_READ_FAILED,
        "wallet activity read failed",
    )


def _require_positive_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("wallet trade limit must be a positive integer")


def _page_items(page: object) -> tuple[object, ...]:
    return sdk_page_items(
        page,
        malformed_error=WalletActivityError(
            WalletActivityIssue.WALLET_READ_FAILED,
            "wallet activity page items are malformed",
        ),
    )
