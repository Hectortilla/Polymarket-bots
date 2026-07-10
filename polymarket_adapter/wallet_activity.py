from __future__ import annotations

from collections.abc import AsyncIterator

from bots.framework.events.wallet_trades import WalletTradeEvent

DEFAULT_WALLET_TRADE_LIMIT = 100


class WalletActivityDataClient:
    async def latest_trades(
        self,
        wallet: str,
        limit: int = DEFAULT_WALLET_TRADE_LIMIT,
    ) -> tuple[WalletTradeEvent, ...]:
        raise NotImplementedError("Implement Data API /trades?user=... fallback.")


class WalletActivityStream:
    async def trades(self, wallets: set[str]) -> AsyncIterator[WalletTradeEvent]:
        raise NotImplementedError("Implement preferred low-latency wallet activity source.")
        yield
