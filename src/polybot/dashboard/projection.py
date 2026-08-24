"""Runtime-event projection shared by terminal and browser dashboards."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from math import isfinite

from polybot.cli.observability.events import (
    DispatchCompleted,
    FillCompleted,
    MarketSettled,
    PortfolioBookBootstrap,
    PortfolioSnapshot,
    RuntimeEvent,
    RuntimeStarted,
    StreamReceived,
)
from polybot.cli.streams.kinds import StreamKind
from polybot.framework.config.models import BotConfig
from polybot.framework.events import OrderStatus
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.performance.contracts.valuation_status import ValuationStatus

from .contracts import (
    DashboardSample,
    EquityChartPoint,
    MarketChartPoint,
    WalletChartPoint,
)
from .history import DashboardHistory
from .markets import DashboardMarkets
from .wallets import DashboardWallets, WalletTimelineEvent


@dataclass(frozen=True, slots=True)
class ProjectionChange:
    accepted_book: BookSnapshot | None = None
    wallet_event: WalletTimelineEvent | None = None


@dataclass(slots=True)
class DashboardProjection:
    """Own the dashboard meanings that must agree across renderers."""

    markets: DashboardMarkets = field(default_factory=DashboardMarkets)
    charts: DashboardHistory = field(default_factory=DashboardHistory)
    wallets: DashboardWallets = field(default_factory=DashboardWallets)
    initial_cash_usdc: Decimal | None = None

    @classmethod
    def from_config(cls, config: BotConfig) -> "DashboardProjection":
        projection = cls(
            markets=DashboardMarkets(
                require_accepted_books=True,
            ),
        )
        projection.configure(config)
        return projection

    def configure(self, config: BotConfig) -> None:
        self.markets.book_max_age_ms = config.event_max_age_ms
        self._start_paper_portfolio(config.paper_portfolio_usdc)
        self.wallets.set_lanes(
            tuple(
                wallet
                for rule in config.stream_rules
                for wallet in rule.wallet_addresses
            )
        )

    def apply(self, event: RuntimeEvent) -> ProjectionChange:
        if isinstance(event, RuntimeStarted):
            self._start_paper_portfolio(event.initial_cash_usdc)
            return ProjectionChange()
        if isinstance(event, StreamReceived):
            return self._stream_received(event)
        if isinstance(event, PortfolioBookBootstrap):
            self._record_book(event.book)
            return ProjectionChange(accepted_book=event.book)
        if isinstance(event, DispatchCompleted):
            return self._dispatch_completed(event)
        if isinstance(event, FillCompleted):
            self._fill_completed(event)
            return ProjectionChange()
        if isinstance(event, MarketSettled):
            self.markets.portfolio = event.portfolio
            token_ids = self.markets.settle(
                condition_id=event.settlement.resolution.condition_id,
                token_ids=event.settlement.resolution.token_ids,
            )
            self.charts.remove_tokens(token_ids)
        return ProjectionChange()

    def sample(self, sampled_at_ms: int) -> DashboardSample:
        self.charts.record_sample(
            sampled_at_ms,
            current_book=self.markets.current_book,
            executable_equity=self.markets.portfolio_valuation(
                sampled_at_ms,
                initial_cash_usdc=self.initial_cash_usdc,
                allow_stale_marks=False,
            ).equity_usdc,
        )
        markets = tuple(
            self._market_chart_point(token_id)
            for token_id in self.charts.chart_tokens
        )
        equity_value = self.charts.executable_equity_history[-1]
        return DashboardSample(
            sampled_at_ms=sampled_at_ms,
            markets=markets,
            equity=EquityChartPoint(
                value=_decimal_chart_value(equity_value),
                status=_sample_status(
                    equity_value,
                    self.charts.executable_equity_stale_history[-1],
                ),
            ),
        )

    def wallet_point(self, source_key: str) -> WalletChartPoint | None:
        event = self.wallets.wallet_timeline_by_source.get(source_key)
        if event is None:
            return None
        return event.chart_point()

    def _market_chart_point(self, token_id: str) -> MarketChartPoint:
        value = self.charts.price_history[token_id][-1]
        return MarketChartPoint(
            token_id=token_id,
            label=self.markets.market_label(token_id),
            value=_decimal_chart_value(value),
            status=_sample_status(
                value,
                self.charts.price_stale_history[token_id][-1],
            ),
            markers=self.charts.trade_marker_history[token_id][-1],
        )

    def _stream_received(self, event: StreamReceived) -> ProjectionChange:
        if event.item.kind is StreamKind.BOOK:
            book = event.item.event
            if self.markets.require_accepted_books:
                self.markets.stage_book(book)
                return ProjectionChange()
            self._record_book(book)
            return ProjectionChange(accepted_book=book)
        if event.item.kind is StreamKind.BOOK_GAP:
            self.markets.invalidate_gap(event.item.event)
            return ProjectionChange()
        if event.item.kind is StreamKind.WALLET and isinstance(
            event.item.event, WalletTradeEvent
        ):
            return ProjectionChange(
                wallet_event=self.wallets.record_trade(event.item.event)
            )
        return ProjectionChange()

    def _dispatch_completed(self, event: DispatchCompleted) -> ProjectionChange:
        accepted_book = None
        if self.markets.require_accepted_books and event.kind is StreamKind.BOOK:
            book = event.item.event
            self.markets.pending_books.pop(book.token_id, None)
            if event.outcome is not None and event.outcome.accepted:
                self._record_book(book)
                accepted_book = book
        wallet_event = None
        if event.kind is StreamKind.WALLET and isinstance(
            event.item.event, WalletTradeEvent
        ):
            if event.outcome is not None:
                self.wallets.mark_dispatch(
                    event.item.event.source_key,
                    accepted=event.outcome.accepted,
                )
            wallet_event = self.wallets.wallet_timeline_by_source.get(
                event.item.event.source_key
            )
        return ProjectionChange(accepted_book, wallet_event)

    def _fill_completed(self, event: FillCompleted) -> None:
        self.markets.portfolio = event.portfolio
        if event.fill.status is OrderStatus.REJECTED:
            return
        self.markets.refresh_fill_mark(event.fill)
        if event.fill.has_execution:
            self.charts.record_trade(event.fill.token_id, event.fill.side)

    def _record_book(self, book: BookSnapshot) -> None:
        self.markets.record_book(book, activate_chart_token=self.charts.activate_token)

    def _start_paper_portfolio(self, initial_cash_usdc: Decimal) -> None:
        self.initial_cash_usdc = initial_cash_usdc
        self.markets.portfolio = PortfolioSnapshot.initial(initial_cash_usdc)


def _decimal_chart_value(value: float) -> Decimal | None:
    return Decimal(str(value)) if isfinite(value) else None


def _sample_status(value: float, stale: bool) -> ValuationStatus:
    if not isfinite(value):
        return ValuationStatus.UNAVAILABLE
    return ValuationStatus.STALE if stale else ValuationStatus.FRESH
