from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable, Iterable

from bots.framework.events.wallet_trades import WalletTradeEvent, WalletTradeKind
from bots.framework.wallets import normalize_wallet_address

from .contracts import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_WALLET_TRADE_LIMIT,
    TRADE_ACTIVITY_TYPE,
    WalletActivityIssue,
    WalletDataClient,
    WalletReadFailure,
    WalletTradeBatch,
    WalletTradeSelector,
    current_time_ms,
)
from .normalization import normalize_wallet_trade, sort_key


class WalletActivityClient:
    """Official-SDK-backed Data API reads for wallet bootstrap/reconciliation."""

    def __init__(
        self,
        client: WalletDataClient,
        *,
        now_ms: Callable[[], int] = current_time_ms,
    ) -> None:
        self._client = client
        self._now_ms = now_ms

    async def latest_trades(
        self,
        wallet: str,
        limit: int = DEFAULT_WALLET_TRADE_LIMIT,
    ) -> tuple[WalletTradeEvent, ...]:
        if limit <= 0:
            return ()
        address = normalize_wallet_address(wallet)
        try:
            paginator = self._client.list_trades(user=address, taker_only=False, page_size=limit)
        except TypeError:
            paginator = self._client.list_trades(user=address, page_size=limit)
        return await _collect_trades(
            paginator,
            limit=limit,
            observed_at_ms=self._now_ms,
            kind=WalletTradeKind.BACKFILL,
            wallet=address,
        )

    async def latest_selector(
        self,
        selector: WalletTradeSelector,
        *,
        start: int | None = None,
        end: int | None = None,
        limit: int = 499,
    ) -> tuple[WalletTradeEvent, ...]:
        paginator = self._client.list_trades(
            user=selector.wallet,
            market=selector.condition_ids or None,
            taker_only=False,
            start=start,
            end=end,
            page_size=limit,
        )
        rows: list[WalletTradeEvent] = []
        async for page in paginator:
            for source in page.items:
                trade = normalize_wallet_trade(
                    source,
                    observed_at_ms=self._now_ms(),
                    kind=WalletTradeKind.RECONCILIATION,
                )
                if trade is not None:
                    rows.append(trade)
        unique = {trade.source_key: trade for trade in rows}
        return tuple(sorted(unique.values(), key=sort_key))

    async def latest_activity(
        self,
        wallet: str,
        limit: int = DEFAULT_WALLET_TRADE_LIMIT,
    ) -> tuple[WalletTradeEvent, ...]:
        if limit <= 0:
            return ()
        address = normalize_wallet_address(wallet)
        paginator = self._client.list_activity(
            user=address,
            activity_types=(TRADE_ACTIVITY_TYPE,),
            page_size=limit,
        )
        return await _collect_trades(
            paginator,
            limit=limit,
            observed_at_ms=self._now_ms,
            kind=WalletTradeKind.RECONCILIATION,
            wallet=address,
        )

    async def latest_trades_many(
        self,
        wallets: Iterable[str],
        *,
        limit: int = DEFAULT_WALLET_TRADE_LIMIT,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> WalletTradeBatch:
        addresses = tuple(dict.fromkeys(normalize_wallet_address(wallet) for wallet in wallets))
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        semaphore = asyncio.Semaphore(max_concurrency)

        async def read_wallet_trades(
            wallet: str,
        ) -> tuple[str, tuple[WalletTradeEvent, ...] | None]:
            async with semaphore:
                try:
                    return wallet, await self.latest_trades(wallet, limit)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return wallet, None

        results = await asyncio.gather(*(read_wallet_trades(wallet) for wallet in addresses))
        return _merge_wallet_results(tuple(results))


async def _collect_trades(
    paginator: AsyncIterable[object],
    *,
    limit: int,
    observed_at_ms: Callable[[], int],
    kind: WalletTradeKind,
    wallet: str,
) -> tuple[WalletTradeEvent, ...]:
    rows: list[WalletTradeEvent] = []
    async for page in paginator:
        for source in page.items:
            trade = normalize_wallet_trade(
                source,
                observed_at_ms=observed_at_ms(),
                kind=kind,
            )
            if trade is not None and trade.wallet == wallet:
                rows.append(trade)
            if len(rows) >= limit:
                return tuple(sorted(rows, key=sort_key))
    return tuple(sorted(rows, key=sort_key))


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


WalletActivityDataClient = WalletActivityClient
