from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from time import monotonic

from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.wallets import normalize_wallet_address

from .client import WalletActivityClient
from .contracts import (
    DATA_TRADES_WINDOW_SECONDS,
    DEFAULT_DATA_TRADES_BUDGET_PER_10S,
    WalletTradeSelector,
    WalletTradeSource,
    WalletActivityError,
    WalletActivityIssue,
    current_time_ms,
)
from .normalization import normalize_stream_event


class SlidingWindowLimiter:
    def __init__(self, budget: int, *, now: Callable[[], float] = monotonic) -> None:
        self._budget = budget
        self._now = now
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = self._now()
                while self._timestamps and now - self._timestamps[0] >= DATA_TRADES_WINDOW_SECONDS:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._budget:
                    self._timestamps.append(now)
                    return
                wait_for = DATA_TRADES_WINDOW_SECONDS - (now - self._timestamps[0])
            await asyncio.sleep(max(wait_for, 0.001))


class WalletActivityStream:
    """Best-effort arbitrary-wallet trades from polling plus an optional push source."""

    def __init__(
        self,
        client: WalletActivityClient | WalletTradeSource | None = None,
        selectors: Iterable[WalletTradeSelector] = (),
        source: WalletTradeSource | None = None,
        *,
        budget_per_10s: int = DEFAULT_DATA_TRADES_BUDGET_PER_10S,
        now_ms: Callable[[], int] = current_time_ms,
    ) -> None:
        if client is not None and not isinstance(client, WalletActivityClient):
            source = client
            client = None
        self._client = client
        self._selectors = tuple(dict.fromkeys(selectors))
        self._source = source
        self._limiter = SlidingWindowLimiter(budget_per_10s)
        self._now_ms = now_ms
        self._wake_conditions: set[str] = set()
        self._wake_event = asyncio.Event()

    def wake_market(self, condition_id: str) -> None:
        if condition_id:
            self._wake_conditions.add(condition_id)
            self._wake_event.set()

    async def trades(self, wallets: frozenset[str] | None = None) -> AsyncIterator[WalletTradeEvent]:
        if wallets is not None and not self._selectors:
            self._selectors = tuple(WalletTradeSelector(wallet=wallet) for wallet in wallets)
        if self._client is None and self._source is None:
            raise WalletActivityError(WalletActivityIssue.STREAM_UNAVAILABLE, "no wallet source is configured")
        queue: asyncio.Queue[WalletTradeEvent] = asyncio.Queue(maxsize=1_000)
        tasks = (
            [asyncio.create_task(self._poll(selector, queue)) for selector in self._selectors]
            if self._client is not None
            else []
        )
        if self._source is not None:
            tasks.append(asyncio.create_task(self._push(queue)))
        seen: set[str] = set()
        order: deque[str] = deque()
        try:
            while any(not task.done() for task in tasks) or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                except TimeoutError:
                    continue
                if event.source_key in seen:
                    continue
                seen.add(event.source_key)
                order.append(event.source_key)
                if len(order) > 10_000:
                    seen.discard(order.popleft())
                yield event
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll(
        self,
        selector: WalletTradeSelector,
        queue: asyncio.Queue[WalletTradeEvent],
    ) -> None:
        last_timestamp_ms = 0
        while True:
            try:
                await self._limiter.acquire()
                end = self._now_ms() // 1_000
                start = max(0, last_timestamp_ms // 1_000 - 1) if last_timestamp_ms else None
                assert self._client is not None
                trades = await self._client.latest_selector(selector, start=start, end=end)
                for trade in trades:
                    await queue.put(trade)
                    last_timestamp_ms = max(last_timestamp_ms, trade.trade_timestamp_ms)
                await self._wait_for_selector(selector)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(DATA_TRADES_WINDOW_SECONDS)

    async def _wait_for_selector(self, selector: WalletTradeSelector) -> None:
        if selector.condition_ids and set(selector.condition_ids) & self._wake_conditions:
            self._wake_conditions.difference_update(selector.condition_ids)
            return
        self._wake_event.clear()
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=0.05)
        except TimeoutError:
            return

    async def _push(self, queue: asyncio.Queue[WalletTradeEvent]) -> None:
        wallets = frozenset(
            normalize_wallet_address(selector.wallet)
            for selector in self._selectors
            if selector.wallet
        )
        if not wallets:
            return
        assert self._source is not None
        async for source in self._source.trades(wallets):
            trade = normalize_stream_event(source, observed_at_ms=self._now_ms())
            if trade is not None and trade.wallet in wallets:
                await queue.put(trade)
