"""Archive-owned context clients used during replay."""

from __future__ import annotations

from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.framework.events import FillEvent, OrderRequest


UNSUPPORTED_WALLET_MESSAGE = (
    "the selected recording contains no wallet activity; wallet-dependent bots "
    "cannot be replayed"
)
UNSUPPORTED_POSITION_MESSAGE = (
    "the selected recording contains no account positions; account-dependent bots "
    "cannot be replayed"
)
UNSUPPORTED_PLANNING_ORDER_MESSAGE = (
    "bots cannot submit or cancel orders while replay stream rules are being planned"
)


class RejectingPlanningBroker:
    async def submit(self, order: OrderRequest) -> FillEvent:
        del order
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            UNSUPPORTED_PLANNING_ORDER_MESSAGE,
        )

    async def cancel_all(self) -> None:
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            UNSUPPORTED_PLANNING_ORDER_MESSAGE,
        )


class RejectingWalletActivityClient:
    async def latest_trades(self, wallet: str, limit: int):
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            UNSUPPORTED_WALLET_MESSAGE,
        )


class RejectingPositionClient:
    async def positions(self, wallet: str):
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            UNSUPPORTED_POSITION_MESSAGE,
        )
