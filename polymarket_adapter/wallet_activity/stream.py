from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from bots.framework.events.wallet_trades import WalletTradeEvent
from bots.framework.wallets import normalize_wallet_address

from .contracts import (
    WalletActivityError,
    WalletActivityIssue,
    WalletTradeSource,
    current_time_ms,
)
from .normalization import normalize_stream_event


class WalletActivityStream:
    """Normalize an injected low-latency source; none is bundled by default."""

    def __init__(self, source: WalletTradeSource | None = None, *, now_ms: Callable[[], int] = current_time_ms) -> None:
        self._source = source
        self._now_ms = now_ms

    async def trades(self, wallets: set[str]) -> AsyncIterator[WalletTradeEvent]:
        if self._source is None:
            raise WalletActivityError(
                WalletActivityIssue.STREAM_UNAVAILABLE,
                "no supported arbitrary-wallet trade stream is configured",
            )
        normalized_wallets = frozenset(normalize_wallet_address(wallet) for wallet in wallets)
        async for source in self._source.trades(normalized_wallets):
            trade = normalize_stream_event(source, observed_at_ms=self._now_ms())
            if trade is not None and trade.wallet in normalized_wallets:
                yield trade
