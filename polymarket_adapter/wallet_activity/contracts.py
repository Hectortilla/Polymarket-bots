from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol

from bots.framework.events.wallet_trades import WalletTradeEvent

DEFAULT_WALLET_TRADE_LIMIT = 100
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_DATA_TRADES_BUDGET_PER_10S = 180
DATA_TRADES_WINDOW_SECONDS = 10
DATA_TRADES_PAGE_SIZE = 499
TRADE_ACTIVITY_TYPE = "TRADE"


def current_time_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


class WalletActivityIssue(StrEnum):
    STREAM_UNAVAILABLE = "stream_unavailable"
    WALLET_READ_FAILED = "wallet_read_failed"


class WalletActivityError(RuntimeError):
    def __init__(self, issue: WalletActivityIssue, detail: str) -> None:
        super().__init__(detail)
        self.issue = issue


@dataclass(frozen=True, slots=True)
class WalletReadFailure:
    wallet: str
    issue: WalletActivityIssue


@dataclass(frozen=True, slots=True)
class WalletTradeBatch:
    trades: tuple[WalletTradeEvent, ...]
    failures: tuple[WalletReadFailure, ...] = ()


class WalletTradeSource(Protocol):
    def trades(self, wallets: frozenset[str]) -> AsyncIterable[object]: ...


class WalletDataClient(Protocol):
    def list_trades(
        self,
        *,
        user: str | None = None,
        market: tuple[str, ...] | None = None,
        taker_only: bool | None = None,
        start: int | None = None,
        end: int | None = None,
        page_size: int,
    ) -> AsyncIterable[object]: ...

    def list_activity(
        self,
        *,
        user: str,
        activity_types: tuple[str, ...],
        page_size: int,
    ) -> AsyncIterable[object]: ...


@dataclass(frozen=True, slots=True)
class WalletTradeSelector:
    wallet: str | None = None
    condition_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.wallet is None and not self.condition_ids:
            raise ValueError("wallet trade selectors require a wallet or markets")
