"""Typed runtime events emitted by the CLI orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from time import monotonic
from typing import TYPE_CHECKING

from polybot.framework.config.models import BotConfig, BotMode
from polybot.framework.activity import BotActivityEvent
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import FillEvent, OrderRequest
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketSettlementEvent

if TYPE_CHECKING:
    from polybot.cli.streams.contracts import StreamEvent, StreamKind
    from polybot.execution.paper.portfolio import PaperPortfolio


class RuntimeState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class BootstrapPhase(StrEnum):
    MARKETS = "markets"
    WALLETS = "wallets"


@dataclass(frozen=True, slots=True)
class BootstrapProgress:
    phase: BootstrapPhase
    completed: int
    total: int
    occurred_at_monotonic: float = field(default_factory=monotonic)

    def __post_init__(self) -> None:
        if self.completed < 0 or self.total < 0:
            raise ValueError("bootstrap progress values must not be negative")
        if self.completed > self.total:
            raise ValueError("bootstrap progress cannot exceed its total")


@dataclass(frozen=True, slots=True)
class RuntimeStarted:
    name: str
    mode: BotMode
    initial_cash_usdc: Decimal
    occurred_at_monotonic: float

    @classmethod
    def from_config(cls, config: BotConfig) -> RuntimeStarted:
        return cls(
            name=config.name,
            mode=config.mode,
            initial_cash_usdc=config.paper_portfolio_usdc,
            occurred_at_monotonic=monotonic(),
        )


@dataclass(frozen=True, slots=True)
class RuntimeStateChanged:
    state: RuntimeState
    occurred_at_monotonic: float


@dataclass(frozen=True, slots=True)
class StreamReceived:
    item: StreamEvent
    occurred_at_monotonic: float


@dataclass(frozen=True, slots=True)
class PortfolioBookBootstrap:
    """A CLOB mark fetched only to value an already-held paper position."""

    book: BookSnapshot
    occurred_at_monotonic: float


@dataclass(frozen=True, slots=True)
class DispatchCompleted:
    item: StreamEvent
    outcome: DispatchOutcome | None
    occurred_at_monotonic: float

    @property
    def kind(self) -> StreamKind:
        return self.item.kind


@dataclass(frozen=True, slots=True)
class StreamHealth:
    queue_depth: int
    peak_queue_depth: int
    book_dispatch_lag_ms: int | None
    book_stale: bool = False
    occurred_at_monotonic: float = field(default_factory=monotonic)
    book_received_count: int = 0
    book_coalesced_count: int = 0


@dataclass(frozen=True, slots=True)
class OrderSubmitted:
    order: OrderRequest
    occurred_at_monotonic: float


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
    occurred_at_monotonic: float


@dataclass(frozen=True, slots=True)
class BrokerFailed:
    order: OrderRequest
    error: str
    occurred_at_monotonic: float


@dataclass(frozen=True, slots=True)
class MarketSettled:
    settlement: MarketSettlementEvent
    portfolio: PortfolioSnapshot
    occurred_at_monotonic: float


@dataclass(frozen=True, slots=True)
class RuntimeFailed:
    error: str
    occurred_at_monotonic: float


RuntimeEvent = (
    RuntimeStarted
    | RuntimeStateChanged
    | BootstrapProgress
    | StreamReceived
    | PortfolioBookBootstrap
    | DispatchCompleted
    | StreamHealth
    | OrderSubmitted
    | FillCompleted
    | BrokerFailed
    | MarketSettled
    | RuntimeFailed
    | BotActivityEvent
)
