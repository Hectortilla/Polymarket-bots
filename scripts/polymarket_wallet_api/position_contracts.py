"""Wallet-position query contract."""

from typing import Final

from .query_contracts import SDK_PAGE_SIZE


POSITION_SIZE_THRESHOLD: Final = 0.1
DEFAULT_MARKET_POSITION_LIMIT: Final = SDK_PAGE_SIZE
MARKET_POSITION_STATUS: Final = "ALL"
MARKET_POSITION_SORT_BY: Final = "TOKENS"
SDK_CASH_PNL_ATTRIBUTE: Final = "cash_pnl"
SDK_CURRENT_VALUE_ATTRIBUTE: Final = "current_value"
SDK_REALIZED_PNL_ATTRIBUTE: Final = "realized_pnl"
