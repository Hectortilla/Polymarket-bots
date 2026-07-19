"""Shared order construction for fixed-dollar wallet-copy examples."""

from __future__ import annotations

from decimal import Decimal

from polybot.framework.events import OrderRequest
from polybot.framework.events.wallet_trades import WalletTradeEvent


COPY_TRADE_NOTIONAL_USDC = Decimal("10")
FIXED_DOLLAR_COPY_REASON = "fixed_dollar_wallet_copy"


def fixed_dollar_copy_order(
    trade: WalletTradeEvent,
    *,
    size: Decimal | None = None,
) -> OrderRequest:
    return OrderRequest(
        token_id=trade.token_id,
        side=trade.side,
        price=trade.price,
        size=size if size is not None else COPY_TRADE_NOTIONAL_USDC / trade.price,
        market_slug=trade.market_slug,
        condition_id=trade.condition_id,
        source_id=trade.source_key,
        reason=FIXED_DOLLAR_COPY_REASON,
    )
