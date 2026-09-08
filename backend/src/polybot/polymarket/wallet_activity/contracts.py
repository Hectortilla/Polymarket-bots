from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.wallets import normalize_wallet_address


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
    def trades(self, wallets: frozenset[str]) -> AsyncIterable[object]:
        ...


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
    ) -> AsyncIterable[object]:
        ...

    def list_activity(
        self,
        *,
        user: str,
        activity_types: tuple[str, ...],
        page_size: int,
    ) -> AsyncIterable[object]:
        ...


@dataclass(frozen=True, slots=True)
class WalletTradeSelector:
    wallet: str | None = None
    condition_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.wallet is None and not self.condition_ids:
            raise ValueError("wallet trade selectors require a wallet or markets")
        if self.wallet is not None:
            if not isinstance(self.wallet, str) or not self.wallet.strip():
                raise ValueError("wallet trade selector wallet is invalid")
            object.__setattr__(
                self,
                "wallet",
                normalize_wallet_address(self.wallet.strip()),
            )
        if not isinstance(self.condition_ids, tuple) or any(
            not isinstance(condition_id, str) or not condition_id.strip()
            for condition_id in self.condition_ids
        ):
            raise ValueError("wallet trade selector markets are invalid")
        normalized_conditions = tuple(
            condition_id.strip() for condition_id in self.condition_ids
        )
        if len(normalized_conditions) != len(set(normalized_conditions)):
            raise ValueError("wallet trade selector markets contain duplicates")
        object.__setattr__(self, "condition_ids", normalized_conditions)

    def accepts(self, trade: WalletTradeEvent) -> bool:
        return (
            (self.wallet is None or trade.wallet == self.wallet)
            and (
                not self.condition_ids
                or trade.condition_id in self.condition_ids
            )
        )
