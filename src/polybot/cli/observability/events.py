"""Typed runtime events emitted by the CLI orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from time import monotonic
from typing import TYPE_CHECKING

from polybot.framework.config import BotConfig, BotMode
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import FillEvent, OrderRequest

if TYPE_CHECKING:
    from polybot.cli.streams import StreamEvent, StreamKind
    from polybot.execution.paper.portfolio import PaperPortfolio


class RuntimeState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeStarted:
    name: str
    mode: BotMode
    initial_cash_usdc: Decimal
    occurred_at: float

    @classmethod
    def from_config(cls, config: BotConfig) -> RuntimeStarted:
        return cls(
            name=config.name,
            mode=config.mode,
            initial_cash_usdc=config.paper_portfolio_usdc,
            occurred_at=monotonic(),
        )


@dataclass(frozen=True, slots=True)
class RuntimeStateChanged:
    state: RuntimeState
    occurred_at: float


@dataclass(frozen=True, slots=True)
class StreamReceived:
    item: StreamEvent
    occurred_at: float


@dataclass(frozen=True, slots=True)
class DispatchCompleted:
    item: StreamEvent
    outcome: DispatchOutcome | None
    occurred_at: float

    @property
    def kind(self) -> StreamKind:
        return self.item.kind


@dataclass(frozen=True, slots=True)
class OrderSubmitted:
    order: OrderRequest
    occurred_at: float


@dataclass(frozen=True, slots=True)
class PortfolioPositionSnapshot:
    token_id: str
    size: Decimal
    average_entry_price: Decimal | None


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    cash_usdc: Decimal
    cumulative_fees_usdc: Decimal
    positions: tuple[PortfolioPositionSnapshot, ...]

    @classmethod
    def from_paper(cls, portfolio: PaperPortfolio) -> PortfolioSnapshot:
        return cls(
            cash_usdc=portfolio.cash_usdc,
            cumulative_fees_usdc=portfolio.cumulative_fees_usdc,
            positions=tuple(
                PortfolioPositionSnapshot(
                    token_id=position.token_id,
                    size=position.size,
                    average_entry_price=position.average_entry_price,
                )
                for position in sorted(portfolio.positions.values(), key=lambda item: item.token_id)
            ),
        )


@dataclass(frozen=True, slots=True)
class FillCompleted:
    order: OrderRequest
    fill: FillEvent
    portfolio: PortfolioSnapshot | None
    latency_ms: int
    occurred_at: float


@dataclass(frozen=True, slots=True)
class BrokerFailed:
    order: OrderRequest
    error: str
    occurred_at: float


@dataclass(frozen=True, slots=True)
class RuntimeFailed:
    error: str
    occurred_at: float


RuntimeEvent = (
    RuntimeStarted
    | RuntimeStateChanged
    | StreamReceived
    | DispatchCompleted
    | OrderSubmitted
    | FillCompleted
    | BrokerFailed
    | RuntimeFailed
)
