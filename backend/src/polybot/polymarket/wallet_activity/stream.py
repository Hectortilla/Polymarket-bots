from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from time import monotonic

from polybot.framework.config.constants import (
    DEFAULT_DATA_TRADES_BUDGET,
    DEFAULT_EVENT_MAX_AGE_MS,
)
from polybot.framework.clock import system_now_ms
from polybot.framework.dedupe import SourceEventDeduper
from polybot.framework.events.wallet_trades import WalletTradeEvent

from .client import PolymarketWalletActivityClient
from .contracts import (
    WalletTradeSelector,
    WalletTradeSource,
    WalletActivityError,
    WalletActivityIssue,
)
from .normalization import normalize_stream_event

DATA_TRADES_RATE_LIMIT_WINDOW_SECONDS = 10
WALLET_STREAM_QUEUE_CAPACITY = 1_000
WALLET_STREAM_POLL_INTERVAL_SECONDS = 0.05


class SlidingWindowLimiter:
    def __init__(self, budget: int, *, now: Callable[[], float] = monotonic) -> None:
        if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
            raise ValueError("rate-limit budget must be a positive integer")
        self._budget = budget
        self._now = now
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = self._now()
                while (
                    self._timestamps
                    and now - self._timestamps[0]
                    >= DATA_TRADES_RATE_LIMIT_WINDOW_SECONDS
                ):
                    self._timestamps.popleft()
                if len(self._timestamps) < self._budget:
                    self._timestamps.append(now)
                    return
                wait_for = DATA_TRADES_RATE_LIMIT_WINDOW_SECONDS - (
                    now - self._timestamps[0]
                )
            await asyncio.sleep(max(wait_for, 0.001))


class WalletActivityStream:
    """Best-effort arbitrary-wallet trades from polling plus an optional push source."""

    def __init__(
        self,
        client: PolymarketWalletActivityClient | None = None,
        selectors: Iterable[WalletTradeSelector] = (),
        *,
        source: WalletTradeSource | None = None,
        budget_per_10s: int = DEFAULT_DATA_TRADES_BUDGET,
        max_trade_age_ms: int = DEFAULT_EVENT_MAX_AGE_MS,
        now_ms: Callable[[], int] = system_now_ms,
    ) -> None:
        if max_trade_age_ms < 0:
            raise ValueError("max_trade_age_ms must be nonnegative")
        self._client = client
        self._selectors = tuple(dict.fromkeys(selectors))
        self._source = source
        self._limiter = SlidingWindowLimiter(budget_per_10s)
        self._max_trade_age_ms = max_trade_age_ms
        self._now_ms = now_ms
        self._wake_conditions: set[str] = set()
        self._wake_event = asyncio.Event()

    def wake_market(self, condition_id: str) -> None:
        if condition_id:
            self._wake_conditions.add(condition_id)
            self._wake_event.set()

    async def trades(
        self, wallets: frozenset[str] | None = None
    ) -> AsyncIterator[WalletTradeEvent]:
        if wallets is not None and not self._selectors:
            self._selectors = tuple(
                WalletTradeSelector(wallet=wallet) for wallet in wallets
            )
        if self._client is None and self._source is None:
            raise WalletActivityError(
                WalletActivityIssue.STREAM_UNAVAILABLE, "no wallet source is configured"
            )
        queue: asyncio.Queue[WalletTradeEvent] = asyncio.Queue(
            maxsize=WALLET_STREAM_QUEUE_CAPACITY
        )
        tasks = (
            [
                asyncio.create_task(self._poll(selector, queue))
                for selector in self._selectors
            ]
            if self._client is not None
            else []
        )
        if self._source is not None:
            tasks.append(asyncio.create_task(self._push(queue)))
        deduper = SourceEventDeduper()
        try:
            while any(not task.done() for task in tasks) or not queue.empty():
                _raise_task_failure(tasks)
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=WALLET_STREAM_POLL_INTERVAL_SECONDS
                    )
                except TimeoutError:
                    continue
                if deduper.claim_if_new(event.source_key):
                    yield event
            _raise_task_failure(tasks)
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
                now_ms = self._now_ms()
                end_epoch_seconds = now_ms // 1_000
                oldest_usable_ms = now_ms - self._max_trade_age_ms
                start_epoch_seconds = max(
                    0,
                    max(last_timestamp_ms, oldest_usable_ms) // 1_000 - 1,
                )
                assert self._client is not None
                trades = await self._client.latest_selector(
                    selector,
                    start_epoch_seconds=start_epoch_seconds,
                    end_epoch_seconds=end_epoch_seconds,
                )
                for trade in trades:
                    if trade.trade_timestamp_ms < oldest_usable_ms:
                        continue
                    await queue.put(trade)
                    last_timestamp_ms = max(
                        last_timestamp_ms,
                        trade.trade_timestamp_ms,
                    )
                await self._wait_for_selector(selector)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(DATA_TRADES_RATE_LIMIT_WINDOW_SECONDS)

    async def _wait_for_selector(self, selector: WalletTradeSelector) -> None:
        if (
            selector.condition_ids
            and set(selector.condition_ids) & self._wake_conditions
        ):
            self._wake_conditions.difference_update(selector.condition_ids)
            return
        self._wake_event.clear()
        try:
            await asyncio.wait_for(
                self._wake_event.wait(), timeout=WALLET_STREAM_POLL_INTERVAL_SECONDS
            )
        except TimeoutError:
            return

    async def _push(self, queue: asyncio.Queue[WalletTradeEvent]) -> None:
        wallets = frozenset(
            selector.wallet
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


def _raise_task_failure(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        if task.done() and not task.cancelled():
            if (error := task.exception()) is not None:
                raise error
