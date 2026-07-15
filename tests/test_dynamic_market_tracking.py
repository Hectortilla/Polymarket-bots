from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from polymarket.models.clob.market_events import (
    MarketResolvedEvent as SdkMarketResolvedEvent,
    MarketResolvedPayload,
)

from polybot.cli.dashboard.state import DashboardState
from polybot.cli.followed_wallets.tracker import FollowedWalletTracker
from polybot.cli.followed_wallets.persistence.serialization import (
    FOLLOW_STATE_VERSION,
    load_states,
)
from polybot.cli.followed_wallets.persistence.schema import (
    FOLLOW_ACTIVE_FIELD,
    FOLLOW_BASELINES_FIELD,
    FOLLOW_BASIS_PRICE_FIELD,
    FOLLOW_BOOTSTRAPPED_FIELD,
    FOLLOW_CHECKPOINT_FIELD,
    FOLLOW_CONDITION_ID_FIELD,
    FOLLOW_EPOCH_FIELD,
    FOLLOW_EPOCH_HISTORY_FIELD,
    FOLLOW_MARKET_SLUG_FIELD,
    FOLLOW_MOVEMENTS_FIELD,
    FOLLOW_POSITIONS_FIELD,
    FOLLOW_PRICE_FIELD,
    FOLLOW_SETTLEMENTS_FIELD,
    FOLLOW_SIDE_FIELD,
    FOLLOW_SIZE_FIELD,
    FOLLOW_SOURCE_IDS_FIELD,
    FOLLOW_SOURCE_KEY_FIELD,
    FOLLOW_STATE_VERSION_FIELD,
    FOLLOW_TOKEN_ID_FIELD,
    FOLLOW_TRADE_TIMESTAMP_MS_FIELD,
    FOLLOW_WALLETS_FIELD,
    FOLLOWED_AT_MS_FIELD,
)
from polybot.cli.observability.events import StreamReceived
from polybot.cli.runner.wallet_dispatch import dispatch_wallet_trade
from polybot.cli.resolution import (
    GAMMA_RECONCILIATION_SOURCE,
    apply_resolution,
    reconcile_resolutions,
    settle_resolved_markets,
)
from polybot.cli.tracking.paper import track_paper_positions
from polybot.cli.tracking.wallets import synchronize_followed_wallets
from polybot.cli.resolution_state import RESOLUTION_LEDGER_VERSION, ResolutionLedger
from polybot.cli.resolution_state import (
    RESOLUTION_LEDGER_VERSION_FIELD,
    RESOLUTION_RECORDS_FIELD,
)
from polybot.cli.resolution import RESOLUTION_RECONCILIATION_SECONDS
from polybot.cli.streams.contracts import StreamKind, WalletStreamEvent
from polybot.cli.streams.merger import merge_streams
from polybot.cli.tracked_markets import MarketInterest, TrackedMarketRegistry
from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.framework.events import Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.base import BaseBot
from polybot.framework.runner import BotRunner
from polybot.framework.events.resolutions import (
    LOSING_PAYOUT_PER_TOKEN,
    NO_OUTCOME,
    WINNING_PAYOUT_PER_TOKEN,
    YES_OUTCOME,
    MarketResolutionEvent,
    MarketSettlementEvent,
)
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.streams import StreamPlan, StreamRelation, StreamRule
from polybot.polymarket.data import DataClient
from polybot.polymarket.types import Market, Position
from polybot.polymarket.ws_market import MARKET_WEBSOCKET_SOURCE, MarketStream

WALLET = "0x0000000000000000000000000000000000000001"


class FakeSubscription:
    def __init__(self, events: tuple[object, ...]) -> None:
        self.events = events

    async def __aenter__(self) -> FakeSubscription:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[object]:
        return self._events()

    async def _events(self) -> AsyncIterator[object]:
        for event in self.events:
            yield event


class FakeStreamClient:
    def __init__(self, events: tuple[object, ...]) -> None:
        self.events = events
        self.specs = []

    async def subscribe(self, spec: object) -> FakeSubscription:
        self.specs.append(spec)
        return FakeSubscription(self.events)


def test_registry_deduplicates_wallet_interests_and_batches_token_changes() -> None:
    async def run() -> tuple[int, int]:
        registry = TrackedMarketRegistry()
        market = _market()
        registry.add(market, MarketInterest.FOLLOWED_WALLET, owner=WALLET)
        revision = registry.revision
        registry.add(
            market,
            MarketInterest.FOLLOWED_WALLET,
            owner="0x0000000000000000000000000000000000000002",
        )
        unchanged_revision = registry.revision
        waiter = asyncio.create_task(
            registry.wait_for_change(revision, batch_seconds=0)
        )
        registry.add(_market("second"), MarketInterest.CONFIGURED)
        return unchanged_revision, await waiter

    unchanged, rebuilt = asyncio.run(run())
    assert unchanged == 1
    assert rebuilt == 2


def test_registry_never_readmits_terminal_conditions() -> None:
    market = _market()
    registry = TrackedMarketRegistry(
        terminal_condition_ids=(market.condition_id,)
    )

    for interest in MarketInterest:
        assert not registry.add(market, interest)
    assert registry.markets == ()
    assert registry.is_terminal(market.condition_id)

    active_registry = TrackedMarketRegistry()
    assert active_registry.add(market, MarketInterest.CONFIGURED)
    assert active_registry.resolve(market.condition_id)
    assert not active_registry.add(market, MarketInterest.BROKER_POSITION)
    assert active_registry.markets == ()


def test_wallet_dispatch_records_trade_and_registers_market_after_acceptance(
    tmp_path,
    dummy_context,
) -> None:
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    tracker.synchronize((WALLET,))
    tracker.bootstrap(WALLET, ())
    registry = TrackedMarketRegistry()
    market = _market()

    class Gamma:
        async def find_by_slug(self, slug):
            return market

    class Clob:
        def __init__(self) -> None:
            self.added: list[Market] = []

        def has_market_slug(self, slug: str) -> bool:
            return False

        def add_market(self, candidate: Market) -> None:
            self.added.append(candidate)

    event = WalletStreamEvent(
        StreamKind.WALLET,
        _trade("dispatch", Side.BUY, "1", "0.4", 1_000),
    )
    runner = BotRunner(BaseBot(), dummy_context, now_ms_fn=lambda: 1_000)
    clob = Clob()

    outcome = asyncio.run(
        dispatch_wallet_trade(
            runner,
            event,
            gamma=Gamma(),  # type: ignore[arg-type]
            clob=clob,  # type: ignore[arg-type]
            registry=registry,
            followed_wallets=tracker,
        )
    )

    assert outcome.accepted
    assert tracker.state(WALLET).source_ids == {_trade("dispatch", Side.BUY, "1", "0.4", 1_000).source_key}  # type: ignore[union-attr]
    assert registry.entries[0].market == market
    assert clob.added == [market]


def test_wallet_dispatch_rejects_trade_without_market_slug(
    dummy_context,
) -> None:
    class Gamma:
        async def find_by_slug(self, slug):
            raise AssertionError("metadata lookup must not guess a missing slug")

    class Clob:
        def has_market_slug(self, slug: str) -> bool:
            raise AssertionError("CLOB must not be mutated for incomplete metadata")

    event = WalletStreamEvent(
        StreamKind.WALLET,
        replace(_trade("missing-slug", Side.BUY, "1", "0.4", 1_000), market_slug=None),
    )
    outcome = asyncio.run(
        dispatch_wallet_trade(
            BotRunner(BaseBot(), dummy_context, now_ms_fn=lambda: 1_000),
            event,
            gamma=Gamma(),  # type: ignore[arg-type]
            clob=Clob(),  # type: ignore[arg-type]
            registry=None,
            followed_wallets=None,
        )
    )

    assert outcome.skip_reason.value == "market_metadata_missing"


def test_wallet_dispatch_skips_terminal_market_before_metadata_or_routing(
    dummy_context,
) -> None:
    market = _market()
    registry = TrackedMarketRegistry(
        terminal_condition_ids=(market.condition_id,)
    )

    class Gamma:
        async def find_by_slug(self, slug):
            raise AssertionError("resolved trades must not fetch market metadata")

    class Clob:
        def has_market_slug(self, slug: str) -> bool:
            raise AssertionError("resolved trades must not register CLOB metadata")

    outcome = asyncio.run(
        dispatch_wallet_trade(
            BotRunner(BaseBot(), dummy_context, now_ms_fn=lambda: 1_000),
            WalletStreamEvent(
                StreamKind.WALLET,
                _trade("resolved", Side.BUY, "1", "0.4", 1_000),
            ),
            gamma=Gamma(),  # type: ignore[arg-type]
            clob=Clob(),  # type: ignore[arg-type]
            registry=registry,
            followed_wallets=None,
        )
    )

    assert outcome.skip_reason.value == "market_resolved"


def test_wallet_bootstrap_keeps_positions_without_executable_books(tmp_path) -> None:
    positions = (
        Position(
            token_id="yes-missing-book",
            size=Decimal("2"),
            condition_id="condition-missing-book",
            market_slug="missing-book",
        ),
        Position(
            token_id="yes-booked",
            size=Decimal("1"),
            condition_id="condition-booked",
            market_slug="booked",
        ),
    )
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    registry = TrackedMarketRegistry()

    class PositionsClient:
        async def positions(self, wallet: str) -> list[Position]:
            return list(positions)

    class Gamma:
        async def find_many(self, slugs):
            return tuple(_market(slug) for slug in slugs)

    class Clob:
        def __init__(self) -> None:
            self.requested: list[str] = []

        def set_markets(self, markets) -> None:
            return None

        async def latest(self, token_id: str) -> BookSnapshot | None:
            self.requested.append(token_id)
            if token_id == "yes-missing-book":
                return None
            return BookSnapshot(
                token_id=token_id,
                bids=(BookLevel(Decimal("0.4"), Decimal("2")),),
                asks=(BookLevel(Decimal("0.6"), Decimal("2")),),
                received_at_ms=1_000,
            )

    clob = Clob()
    asyncio.run(
        synchronize_followed_wallets(
            {WALLET: None},
            tracker,
            PositionsClient(),  # type: ignore[arg-type]
            Gamma(),  # type: ignore[arg-type]
            clob,  # type: ignore[arg-type]
            registry,
        )
    )

    state = tracker.state(WALLET)
    assert state is not None and state.bootstrapped
    assert clob.requested == ["yes-missing-book", "yes-booked"]
    assert state.baselines["yes-missing-book"].basis_price is None
    assert state.baselines["yes-booked"].basis_price == Decimal("0.4")
    assert tracker.gross_pnl(
        WALLET,
        {"yes-missing-book": Decimal("0.5"), "yes-booked": Decimal("0.5")},
    ) is None
    assert tracker.mark_baseline("yes-missing-book", Decimal("0.3"))
    assert tracker.gross_pnl(
        WALLET,
        {"yes-missing-book": Decimal("0.5"), "yes-booked": Decimal("0.5")},
    ) == Decimal("0.5")


def test_filtered_wallet_bootstrap_reads_only_rule_markets(tmp_path) -> None:
    positions = (
        Position(
            token_id="yes-allowed",
            size=Decimal("1"),
            condition_id="condition-allowed",
            market_slug="allowed",
        ),
        Position(
            token_id="yes-outside-rule",
            size=Decimal("1"),
            condition_id="condition-outside-rule",
            market_slug="outside-rule",
        ),
    )
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    registry = TrackedMarketRegistry()

    class PositionsClient:
        def __init__(self) -> None:
            self.requests: list[tuple[str, tuple[str, ...] | None]] = []

        async def positions(
            self,
            wallet: str,
            *,
            condition_ids: tuple[str, ...] | None = None,
        ) -> list[Position]:
            self.requests.append((wallet, condition_ids))
            return list(positions)

    class Gamma:
        async def find_many(self, slugs):
            return tuple(_market(slug) for slug in slugs)

    class Clob:
        def __init__(self) -> None:
            self.requested: list[str] = []

        def set_markets(self, markets) -> None:
            return None

        async def latest(self, token_id: str) -> BookSnapshot | None:
            self.requested.append(token_id)
            return None

    positions_client = PositionsClient()
    clob = Clob()
    asyncio.run(
        synchronize_followed_wallets(
            {WALLET: frozenset({"allowed"})},
            tracker,
            positions_client,  # type: ignore[arg-type]
            Gamma(),  # type: ignore[arg-type]
            clob,  # type: ignore[arg-type]
            registry,
            resolved_markets=(_market("allowed"),),
        )
    )

    assert positions_client.requests == [(WALLET, ("condition-allowed",))]
    assert clob.requested == ["yes-allowed"]
    assert registry.markets == (_market("allowed"),)
    state = tracker.state(WALLET)
    assert state is not None
    assert tuple(state.baselines) == ("yes-allowed",)


def test_filtered_wallet_scope_is_strict_while_independent_wallet_can_discover() -> None:
    other_wallet = "0x0000000000000000000000000000000000000002"
    scopes = StreamPlan(
        current=(
            StreamRule(StreamRelation.FILTERED, ("allowed",), (WALLET,)),
            StreamRule(StreamRelation.INDEPENDENT, (), (other_wallet,)),
        )
    ).wallet_discovery_scopes()
    assert scopes == {WALLET: frozenset({"allowed"}), other_wallet: None}


def test_gamma_reconciliation_emits_missed_resolution_immediately() -> None:
    registry = TrackedMarketRegistry()
    registry.add(_market(), MarketInterest.CONFIGURED)
    resolved = replace(
        _market(),
        resolved=True,
        winning_token_id="yes-market",
        winning_outcome=YES_OUTCOME,
    )

    class Gamma:
        async def find_many(self, slugs):
            return (resolved,)

    async def run() -> MarketResolutionEvent:
        events = reconcile_resolutions(
            registry,
            Gamma(),  # type: ignore[arg-type]
            interval_seconds=RESOLUTION_RECONCILIATION_SECONDS,
            now_ms=lambda: 3_000,
        )
        try:
            return await anext(events)
        finally:
            await events.aclose()

    event = asyncio.run(run())
    assert event.source == GAMMA_RECONCILIATION_SOURCE
    assert event.resolved_at_ms == 3_000


def test_gamma_reconciliation_continues_after_provider_failure() -> None:
    registry = TrackedMarketRegistry()
    registry.add(_market(), MarketInterest.CONFIGURED)

    class Gamma:
        async def find_many(self, slugs):
            raise RuntimeError("temporary Gamma failure")

    async def run() -> None:
        events = reconcile_resolutions(
            registry,
            Gamma(),  # type: ignore[arg-type]
            interval_seconds=0,
        )
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(anext(events), timeout=0.01)
        finally:
            await events.aclose()

    asyncio.run(run())


def test_async_persistence_constructors_load_without_blocking(tmp_path) -> None:
    async def run() -> tuple[tuple[str, ...], bool]:
        tracker = await FollowedWalletTracker.create(tmp_path / "follow.json")
        ledger = await ResolutionLedger.create(tmp_path / "resolutions.json")
        return tracker.active_wallets, ledger.contains(_resolution())

    assert asyncio.run(run()) == ((), False)


def test_broker_position_interest_can_add_market_outside_current_plan() -> None:
    registry = TrackedMarketRegistry()

    class Portfolio:
        positions = {"yes-market": object()}

    class Paper:
        portfolio = Portfolio()
        position_market_refs = {"yes-market": ("market", "condition-market")}

    class Gamma:
        async def find_many(self, slugs):
            return (_market(),)

    asyncio.run(
        track_paper_positions(
            Paper(),  # type: ignore[arg-type]
            registry,
            Gamma(),  # type: ignore[arg-type]
        )
    )
    assert registry.markets == (_market(),)
    assert registry.entries[0].interests == {MarketInterest.BROKER_POSITION}


def test_broker_position_identity_mismatch_is_rejected() -> None:
    registry = TrackedMarketRegistry()

    class Portfolio:
        positions = {"yes-market"}

    class Paper:
        portfolio = Portfolio()
        position_market_refs = {"yes-market": ("market", "wrong-condition")}

    class Gamma:
        async def find_many(self, slugs):
            return (_market(),)

    with pytest.raises(RuntimeError, match="unresolved market identity"):
        asyncio.run(
            track_paper_positions(
                Paper(),  # type: ignore[arg-type]
                registry,
                Gamma(),  # type: ignore[arg-type]
            )
        )
    assert registry.entries == ()


def test_market_stream_enables_custom_events_and_normalizes_resolution() -> None:
    sdk_event = SdkMarketResolvedEvent.model_construct(
        topic="market",
        type="market_resolved",
        payload=MarketResolvedPayload.model_construct(
            id="1",
            market="condition-market",
            token_ids=("yes-market", "no-market"),
            winning_token_id="yes-market",
            winning_outcome=YES_OUTCOME,
            timestamp=datetime.fromtimestamp(2, tz=UTC),
        ),
    )
    client = FakeStreamClient((sdk_event,))

    async def run() -> list[object]:
        stream = MarketStream(client, markets=(_market(),))  # type: ignore[arg-type]
        return [event async for event in stream.events({"yes-market", "no-market"})]

    events = asyncio.run(run())
    assert client.specs[0].custom_feature_enabled is True
    assert events == [
        MarketResolutionEvent(
            condition_id="condition-market",
            market_slug="market",
            token_ids=("yes-market", "no-market"),
            winning_token_id="yes-market",
            winning_outcome=YES_OUTCOME,
            resolved_at_ms=2_000,
            source=MARKET_WEBSOCKET_SOURCE,
        )
    ]


def test_market_stream_rejects_resolution_with_mismatched_identity() -> None:
    sdk_event = SdkMarketResolvedEvent.model_construct(
        topic="market",
        type="market_resolved",
        payload=MarketResolvedPayload.model_construct(
            id="1",
            market="condition-market",
            token_ids=("yes-market", "wrong-token"),
            winning_token_id="wrong-token",
            winning_outcome=NO_OUTCOME,
            timestamp=None,
        ),
    )

    async def run() -> list[object]:
        stream = MarketStream(
            FakeStreamClient((sdk_event,)),  # type: ignore[arg-type]
            markets=(_market(),),
        )
        return [event async for event in stream.events({"yes-market", "no-market"})]

    assert asyncio.run(run()) == []


def test_market_stream_rejects_resolution_with_invalid_timestamp() -> None:
    class InvalidTimestamp:
        def timestamp(self) -> float:
            return float("nan")

    sdk_event = SdkMarketResolvedEvent.model_construct(
        topic="market",
        type="market_resolved",
        payload=MarketResolvedPayload.model_construct(
            id="1",
            market="condition-market",
            token_ids=("yes-market", "no-market"),
            winning_token_id="yes-market",
            winning_outcome=YES_OUTCOME,
            timestamp=InvalidTimestamp(),
        ),
    )

    async def run() -> list[object]:
        stream = MarketStream(
            FakeStreamClient((sdk_event,)),  # type: ignore[arg-type]
            markets=(_market(),),
        )
        return [event async for event in stream.events({"yes-market", "no-market"})]

    assert asyncio.run(run()) == []


def test_follow_bootstrap_replay_restart_and_new_epoch(tmp_path) -> None:
    path = tmp_path / "follow.json"
    tracker = FollowedWalletTracker(path, now_ms=lambda: 1_000)
    assert tracker.synchronize((WALLET,)) == (WALLET,)
    tracker.bootstrap(
        WALLET,
        (
            (
                Position(
                    token_id="yes-market",
                    size=Decimal("2"),
                    condition_id="condition-market",
                    market_slug="market",
                    outcome=YES_OUTCOME,
                ),
                Decimal("0.4"),
            ),
        ),
    )
    assert tracker.gross_pnl(WALLET, {"yes-market": Decimal("0.4")}) == 0

    later_sell = _trade("sell", Side.SELL, "1", "0.6", 20)
    earlier_buy = _trade("buy", Side.BUY, "2", "0.2", 10)
    assert tracker.record_trade(later_sell)
    assert tracker.record_trade(earlier_buy)
    assert not tracker.record_trade(earlier_buy)
    assert tracker.gross_pnl(WALLET, {"yes-market": Decimal("0.5")}) == Decimal("0.9")

    restored = FollowedWalletTracker(path)
    assert restored.gross_pnl(WALLET, {"yes-market": Decimal("0.5")}) == Decimal("0.9")
    assert restored.synchronize(()) == ()
    assert restored.synchronize((WALLET,)) == (WALLET,)
    assert restored.state(WALLET).epoch == 2  # type: ignore[union-attr]
    assert restored.state(WALLET).bootstrapped is False  # type: ignore[union-attr]
    assert restored.open_market_slugs() == ("market",)
    assert restored.settle(_resolution())[0].cash_payout_usdc == Decimal("3")


def test_follow_and_paper_resolution_settle_contractual_payout(tmp_path) -> None:
    tracker = FollowedWalletTracker(tmp_path / "follow.json", now_ms=lambda: 1_000)
    tracker.synchronize((WALLET,))
    tracker.bootstrap(
        WALLET,
        (
            (
                Position(
                    token_id="yes-market",
                    size=Decimal("2"),
                    condition_id="condition-market",
                    market_slug="market",
                ),
                Decimal("0.4"),
            ),
        ),
    )
    event = _resolution()
    followed = tracker.settle(event)
    assert followed[0].cash_payout_usdc == Decimal("2")
    assert tracker.gross_pnl(WALLET, {}) == Decimal("1.2")

    paper = PaperPortfolio(Decimal("100"))
    paper.apply_fill(
        token_id="yes-market",
        side=Side.BUY,
        filled_size=Decimal("2"),
        average_price=Decimal("0.4"),
        fee_usdc=Decimal("0"),
    )
    settlement = paper.settle_market(event)
    assert settlement[0].cash_payout_usdc == Decimal("2")
    assert paper.cash_usdc == Decimal("101.2")
    assert paper.positions == {}


def test_paper_settlement_handles_winners_losers_and_short_positions() -> None:
    losing = PaperPortfolio(Decimal("100"))
    losing.apply_fill(
        token_id="yes-market",
        side=Side.BUY,
        filled_size=Decimal("2"),
        average_price=Decimal("0.4"),
        fee_usdc=Decimal("0"),
    )
    losing_event = replace(
        _resolution(), winning_token_id="no-market", winning_outcome=NO_OUTCOME
    )
    losing_settlement = losing.settle_market(losing_event)
    assert losing_settlement[0].payout_per_token == LOSING_PAYOUT_PER_TOKEN
    assert losing_settlement[0].cash_payout_usdc == Decimal("0")
    assert losing_settlement[0].realized_pnl_usdc == Decimal("-0.8")
    assert losing.cash_usdc == Decimal("99.2")

    short = PaperPortfolio(Decimal("100"))
    short.apply_fill(
        token_id="yes-market",
        side=Side.SELL,
        filled_size=Decimal("2"),
        average_price=Decimal("0.4"),
        fee_usdc=Decimal("0"),
    )
    short_settlement = short.settle_market(_resolution())
    assert short_settlement[0].cash_payout_usdc == Decimal("-2")
    assert short_settlement[0].realized_pnl_usdc == Decimal("-1.2")
    assert short.cash_usdc == Decimal("98.8")


def test_follow_replay_handles_weighted_basis_and_reversal(tmp_path) -> None:
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    tracker.synchronize((WALLET,))
    tracker.bootstrap(WALLET, ())
    assert tracker.record_trade(_trade("buy-1", Side.BUY, "2", "0.2", 10))
    assert tracker.record_trade(_trade("buy-2", Side.BUY, "2", "0.4", 20))
    assert tracker.record_trade(_trade("reverse", Side.SELL, "5", "0.5", 30))

    position = tracker.positions(WALLET)[0]
    assert position.size == Decimal("-1")
    assert position.average_basis == Decimal("0.5")
    assert tracker.gross_pnl(WALLET, {"yes-market": Decimal("0.4")}) == Decimal("0.9")
    settled = tracker.settle(_resolution())
    assert settled[0].cash_payout_usdc == Decimal("-1")
    assert tracker.gross_pnl(WALLET, {}) == Decimal("0.3")


def test_follow_unresolved_basis_remains_unrealized(tmp_path) -> None:
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    tracker.synchronize((WALLET,))
    tracker.bootstrap(
        WALLET,
        (
            (
                Position(
                    token_id="yes-market",
                    size=Decimal("2"),
                    condition_id="condition-market",
                    market_slug="market",
                ),
                None,
            ),
        ),
    )
    assert tracker.gross_pnl(WALLET, {"yes-market": Decimal("0.5")}) is None
    settled = tracker.settle(_resolution())
    assert settled[0].realized_pnl_usdc is None
    assert tracker.gross_pnl(WALLET, {}) is None


def test_resolution_persists_before_hook_and_is_idempotent(tmp_path) -> None:
    registry = TrackedMarketRegistry()
    registry.add(_market(), MarketInterest.CONFIGURED)
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    ledger = ResolutionLedger(tmp_path / "resolutions.json")
    calls: list[str] = []

    class Paper:
        portfolio = PaperPortfolio(Decimal("100"))

        def settle_market(self, event):
            calls.append("paper")
            return ()

    class Runner:
        async def dispatch_market_resolution(self, event):
            assert ledger.contains(event)
            calls.append("hook")

    async def run() -> None:
        await apply_resolution(
            Runner(),  # type: ignore[arg-type]
            _resolution(),
            registry=registry,
            followed_wallets=tracker,
            paper_broker=Paper(),  # type: ignore[arg-type]
            resolution_ledger=ledger,
            observer=None,
        )
        await apply_resolution(
            Runner(),  # type: ignore[arg-type]
            _resolution(),
            registry=registry,
            followed_wallets=tracker,
            paper_broker=Paper(),  # type: ignore[arg-type]
            resolution_ledger=ledger,
            observer=None,
        )

    asyncio.run(run())
    assert calls == ["paper", "hook"]
    assert registry.entries == ()


def test_bootstrap_settles_resolved_market_before_any_subscription(tmp_path) -> None:
    resolved_market = replace(
        _market(),
        resolved=True,
        winning_token_id="yes-market",
        winning_outcome=YES_OUTCOME,
    )
    registry = TrackedMarketRegistry()
    registry.add(resolved_market, MarketInterest.CONFIGURED)
    ledger = ResolutionLedger(tmp_path / "resolutions.json")
    calls: list[str] = []

    class Paper:
        portfolio = PaperPortfolio(Decimal("100"))

        def settle_market(self, event):
            calls.append("paper")
            return ()

    class Runner:
        async def dispatch_market_resolution(self, event):
            calls.append("hook")

    asyncio.run(
        settle_resolved_markets(
            Runner(),  # type: ignore[arg-type]
            registry=registry,
            followed_wallets=FollowedWalletTracker(tmp_path / "follow.json"),
            paper_broker=Paper(),  # type: ignore[arg-type]
            resolution_ledger=ledger,
            observer=None,
        )
    )

    assert calls == ["paper", "hook"]
    assert registry.markets == ()
    assert registry.is_terminal(resolved_market.condition_id)
    assert ledger.resolved_condition_ids == {resolved_market.condition_id}


def test_resolution_rolls_back_settlement_when_ledger_record_fails(tmp_path) -> None:
    registry = TrackedMarketRegistry()
    registry.add(_market(), MarketInterest.CONFIGURED)
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    tracker.synchronize((WALLET,))
    tracker.bootstrap(
        WALLET,
        (
            (
                Position(
                    token_id="yes-market",
                    size=Decimal("1"),
                    condition_id="condition-market",
                    market_slug="market",
                ),
                Decimal("0.4"),
            ),
        ),
    )

    class Paper:
        def __init__(self) -> None:
            self.portfolio = PaperPortfolio(Decimal("100"))
            self.portfolio.apply_fill(
                token_id="yes-market",
                side=Side.BUY,
                filled_size=Decimal("1"),
                average_price=Decimal("0.4"),
                fee_usdc=Decimal("0"),
            )

        def settle_market(self, event):
            return self.portfolio.settle_market(event)

    class Ledger:
        def __init__(self) -> None:
            self.fail = True

        def contains(self, event):
            return False

        def record(self, settlement):
            if self.fail:
                self.fail = False
                raise OSError("ledger unavailable")

    class Runner:
        async def dispatch_market_resolution(self, event):
            return None

    paper = Paper()
    ledger = Ledger()
    with pytest.raises(OSError, match="ledger unavailable"):
        asyncio.run(
            apply_resolution(
                Runner(),  # type: ignore[arg-type]
                _resolution(),
                registry=registry,
                followed_wallets=tracker,
                paper_broker=paper,  # type: ignore[arg-type]
                resolution_ledger=ledger,  # type: ignore[arg-type]
                observer=None,
            )
        )

    assert paper.portfolio.positions["yes-market"].size == Decimal("1")
    assert tracker.state(WALLET).settlements == []  # type: ignore[union-attr]
    assert registry.entries

    settlement = asyncio.run(
        apply_resolution(
            Runner(),  # type: ignore[arg-type]
            _resolution(),
            registry=registry,
            followed_wallets=tracker,
            paper_broker=paper,  # type: ignore[arg-type]
            resolution_ledger=ledger,  # type: ignore[arg-type]
            observer=None,
        )
    )
    assert settlement is not None


def test_resolution_rolls_back_when_followed_settlement_fails(tmp_path) -> None:
    registry = TrackedMarketRegistry()
    registry.add(_market(), MarketInterest.CONFIGURED)
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    tracker.synchronize((WALLET,))
    tracker.bootstrap(
        WALLET,
        (
            (
                Position(
                    token_id="yes-market",
                    size=Decimal("1"),
                    condition_id="condition-market",
                    market_slug="market",
                ),
                Decimal("0.4"),
            ),
        ),
    )
    followed_snapshot = tracker.snapshot()

    class FailingFollowed:
        def snapshot(self):
            return tracker.snapshot()

        def restore(self, snapshot):
            tracker.restore(snapshot)

        def settle(self, event):
            tracker.settle(event)
            raise RuntimeError("followed settlement unavailable")

    class Paper:
        def __init__(self) -> None:
            self.portfolio = PaperPortfolio(Decimal("100"))
            self.portfolio.apply_fill(
                token_id="yes-market",
                side=Side.BUY,
                filled_size=Decimal("1"),
                average_price=Decimal("0.4"),
                fee_usdc=Decimal("0"),
            )

        def settle_market(self, event):
            return self.portfolio.settle_market(event)

    class Ledger:
        def contains(self, event):
            return False

        def record(self, settlement):
            raise AssertionError("ledger must not record a failed settlement")

    class Runner:
        async def dispatch_market_resolution(self, event):
            raise AssertionError("resolution hook must not run")

    paper = Paper()
    with pytest.raises(RuntimeError, match="followed settlement unavailable"):
        asyncio.run(
            apply_resolution(
                Runner(),  # type: ignore[arg-type]
                _resolution(),
                registry=registry,
                followed_wallets=FailingFollowed(),  # type: ignore[arg-type]
                paper_broker=paper,  # type: ignore[arg-type]
                resolution_ledger=Ledger(),  # type: ignore[arg-type]
                observer=None,
            )
        )

    assert paper.portfolio.positions["yes-market"].size == Decimal("1")
    assert tracker.snapshot() == followed_snapshot
    assert registry.entries


def test_followed_wallet_state_rejects_malformed_nested_payload() -> None:
    with pytest.raises(ValueError, match="epoch"):
        load_states(
            {
                FOLLOW_STATE_VERSION_FIELD: FOLLOW_STATE_VERSION,
                FOLLOW_WALLETS_FIELD: {
                    WALLET: {
                        FOLLOW_EPOCH_FIELD: "one",
                        FOLLOW_ACTIVE_FIELD: True,
                        FOLLOWED_AT_MS_FIELD: 0,
                        FOLLOW_BOOTSTRAPPED_FIELD: False,
                        FOLLOW_BASELINES_FIELD: [],
                        FOLLOW_MOVEMENTS_FIELD: [],
                        FOLLOW_SOURCE_IDS_FIELD: [],
                        FOLLOW_CHECKPOINT_FIELD: None,
                        FOLLOW_SETTLEMENTS_FIELD: [],
                        FOLLOW_EPOCH_HISTORY_FIELD: [],
                    }
                },
            }
        )


@pytest.mark.parametrize(
    ("section", "value"),
    (
        (
            FOLLOW_BASELINES_FIELD,
            [
                {
                    FOLLOW_CONDITION_ID_FIELD: "condition",
                    FOLLOW_TOKEN_ID_FIELD: "token",
                    FOLLOW_MARKET_SLUG_FIELD: "market",
                    FOLLOW_SIZE_FIELD: "bad",
                    FOLLOW_BASIS_PRICE_FIELD: None,
                }
            ],
        ),
        (
            FOLLOW_MOVEMENTS_FIELD,
            [
                {
                    FOLLOW_CONDITION_ID_FIELD: "condition",
                    FOLLOW_TOKEN_ID_FIELD: "token",
                    FOLLOW_SIDE_FIELD: "HOLD",
                    FOLLOW_SIZE_FIELD: "1",
                    FOLLOW_PRICE_FIELD: "0.5",
                    FOLLOW_TRADE_TIMESTAMP_MS_FIELD: 1,
                    FOLLOW_SOURCE_KEY_FIELD: "source",
                }
            ],
        ),
        (
            FOLLOW_SETTLEMENTS_FIELD,
            [
                {
                    FOLLOW_CONDITION_ID_FIELD: "condition",
                    "winning_token_id": "token",
                    "resolved_at_ms": 1,
                    FOLLOW_POSITIONS_FIELD: [],
                    FOLLOW_BASELINES_FIELD: "bad",
                    FOLLOW_MOVEMENTS_FIELD: [],
                }
            ],
        ),
        (FOLLOW_EPOCH_HISTORY_FIELD, [{FOLLOW_EPOCH_FIELD: "bad"}]),
    ),
)
def test_followed_wallet_state_rejects_malformed_nested_sections(
    section: str,
    value: object,
) -> None:
    state = {
        FOLLOW_EPOCH_FIELD: 1,
        FOLLOW_ACTIVE_FIELD: True,
        FOLLOWED_AT_MS_FIELD: 0,
        FOLLOW_BOOTSTRAPPED_FIELD: False,
        FOLLOW_BASELINES_FIELD: [],
        FOLLOW_MOVEMENTS_FIELD: [],
        FOLLOW_SOURCE_IDS_FIELD: [],
        FOLLOW_CHECKPOINT_FIELD: None,
        FOLLOW_SETTLEMENTS_FIELD: [],
        FOLLOW_EPOCH_HISTORY_FIELD: [],
    }
    state[section] = value
    with pytest.raises(ValueError):
        load_states(
            {
                FOLLOW_STATE_VERSION_FIELD: FOLLOW_STATE_VERSION,
                FOLLOW_WALLETS_FIELD: {WALLET: state},
            }
        )


def test_resolution_ledger_rejects_conflicting_winner_without_mutation(
    tmp_path,
) -> None:
    ledger = ResolutionLedger(tmp_path / "resolutions.json")
    event = _resolution()
    ledger.record(
        MarketSettlementEvent(
            resolution=event,
            paper_positions=(),
            followed_wallet_positions=(),
            settled_at_ms=2_001,
        )
    )
    conflicting = replace(
        event, winning_token_id="no-market", winning_outcome=NO_OUTCOME
    )

    with pytest.raises(ValueError, match="conflicting resolution"):
        ledger.contains(conflicting)
    assert ledger.contains(event) is True


def test_resolution_ledger_rejects_malformed_persisted_record(tmp_path) -> None:
    path = tmp_path / "resolutions.json"
    path.write_text(
        json.dumps(
            {
                RESOLUTION_LEDGER_VERSION_FIELD: RESOLUTION_LEDGER_VERSION,
                RESOLUTION_RECORDS_FIELD: {
                    "condition-market": {
                        "winning_token_id": "yes-market",
                        "winning_outcome": YES_OUTCOME,
                        "resolved_at_ms": "bad",
                        "settled_at_ms": 2_001,
                        "source": "test",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="resolution ledger"):
        ResolutionLedger(path)


def test_resolution_ledger_rejects_unsupported_version(tmp_path) -> None:
    path = tmp_path / "resolutions.json"
    path.write_text(
        json.dumps({RESOLUTION_LEDGER_VERSION_FIELD: RESOLUTION_LEDGER_VERSION + 1}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported resolution ledger version"):
        ResolutionLedger(path)


def test_resolution_identity_mismatch_fails_closed_and_unknown_resolution_is_ignored(
    tmp_path,
) -> None:
    registry = TrackedMarketRegistry()
    registry.add(_market(), MarketInterest.CONFIGURED)
    tracker = FollowedWalletTracker(tmp_path / "follow.json")
    ledger = ResolutionLedger(tmp_path / "resolutions.json")
    mismatched = replace(_resolution(), market_slug="other-market")
    ledger.record(
        MarketSettlementEvent(
            resolution=_resolution(),
            paper_positions=(),
            followed_wallet_positions=(),
            settled_at_ms=2_001,
        )
    )

    class Runner:
        async def dispatch_market_resolution(self, event):
            raise AssertionError("mismatched resolutions must not reach the hook")

    with pytest.raises(ValueError, match="resolution identity"):
        asyncio.run(
            apply_resolution(
                Runner(),  # type: ignore[arg-type]
                mismatched,
                registry=registry,
                followed_wallets=tracker,
                paper_broker=PaperPortfolio(Decimal("100")),  # type: ignore[arg-type]
                resolution_ledger=ledger,
                observer=None,
            )
        )
    assert registry.entries
    unknown = replace(_resolution(), condition_id="unknown-condition")
    assert (
        asyncio.run(
            apply_resolution(
                Runner(),  # type: ignore[arg-type]
                unknown,
                registry=registry,
                followed_wallets=tracker,
                paper_broker=PaperPortfolio(Decimal("100")),  # type: ignore[arg-type]
                resolution_ledger=ledger,
                observer=None,
            )
        )
        is None
    )
    assert registry.entries


def test_resolution_stream_events_are_not_coalesced_or_charted() -> None:
    event = _resolution()

    async def source() -> AsyncIterator[MarketResolutionEvent]:
        yield event
        yield event

    async def run():
        return [item async for item in merge_streams(((StreamKind.BOOK, source()),))]

    items = asyncio.run(run())
    assert [item.kind for item in items] == [
        StreamKind.RESOLUTION,
        StreamKind.RESOLUTION,
    ]

    state = DashboardState()
    state.apply(StreamReceived(items[0], 1.0))
    state.sample(80, now_ms=2_000)
    assert tuple(state.chart_tokens) == ()
    assert state.price_history == {}


def test_data_client_normalizes_current_positions_and_rejects_malformed() -> None:
    class Page:
        def __init__(self, items) -> None:
            self.items = items

    class Paginator:
        def __init__(self, items) -> None:
            self.items = items

        def __aiter__(self):
            async def pages():
                yield Page(self.items)

            return pages()

    class Client:
        def __init__(self, items) -> None:
            self.items = items

        def list_positions(self, **kwargs):
            return Paginator(self.items)

    valid = type(
        "SdkPosition",
        (),
        {
            "token_id": "yes-market",
            "condition_id": "condition-market",
            "slug": "market",
            "size": Decimal("2"),
            "avg_price": Decimal("0.3"),
            "cur_price": Decimal("0.4"),
            "outcome": YES_OUTCOME,
        },
    )()

    assert (
        asyncio.run(DataClient(Client((valid,))).positions(WALLET))[0].condition_id
        == "condition-market"
    )
    malformed = type(
        "BadPosition",
        (),
        {
            "token_id": None,
            "condition_id": "condition-market",
            "slug": "market",
            "size": Decimal("2"),
            "avg_price": None,
            "cur_price": None,
        },
    )()
    try:
        asyncio.run(DataClient(Client((malformed,))).positions(WALLET))
    except ValueError:
        pass
    else:
        raise AssertionError("malformed position must fail closed")
    invalid_outcome = type(
        "InvalidOutcome",
        (),
        {
            "token_id": "yes-market",
            "condition_id": "condition-market",
            "slug": "market",
            "size": Decimal("2"),
            "avg_price": Decimal("0.3"),
            "cur_price": Decimal("0.4"),
            "outcome": 1,
        },
    )()
    with pytest.raises(ValueError):
        asyncio.run(DataClient(Client((invalid_outcome,))).positions(WALLET))
    arbitrary_outcome = type(
        "ArbitraryOutcome",
        (),
        {
            "token_id": "up-market",
            "condition_id": "condition-market",
            "slug": "btc-up-or-down",
            "size": Decimal("2"),
            "avg_price": Decimal("0.3"),
            "cur_price": Decimal("0.4"),
            "outcome": "Up",
        },
    )()
    assert (
        asyncio.run(DataClient(Client((arbitrary_outcome,))).positions(WALLET))[0].outcome
        == "Up"
    )


def test_data_client_passes_filtered_market_condition_ids_to_sdk() -> None:
    class Client:
        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []

        def list_positions(self, **kwargs):
            self.requests.append(kwargs)

            class Paginator:
                def __aiter__(self):
                    async def pages():
                        yield type("Page", (), {"items": []})()

                    return pages()

            return Paginator()

    client = Client()
    asyncio.run(
        DataClient(client).positions(
            WALLET,
            condition_ids=("condition-allowed", "condition-other"),
        )
    )

    assert client.requests == [
        {
            "user": WALLET,
            "market": ("condition-allowed", "condition-other"),
            "size_threshold": 0,
            "page_size": 100,
        }
    ]

    client.requests.clear()
    asyncio.run(DataClient(client).positions(WALLET))
    assert client.requests == [
        {"user": WALLET, "size_threshold": 0, "page_size": 100}
    ]


def _market(slug: str = "market") -> Market:
    return Market(
        condition_id=f"condition-{slug}",
        slug=slug,
        question=slug,
        yes_token_id=f"yes-{slug}",
        no_token_id=f"no-{slug}",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0"),
    )


def _trade(
    source_id: str,
    side: Side,
    size: str,
    price: str,
    timestamp: int,
) -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet=WALLET,
        condition_id="condition-market",
        token_id="yes-market",
        side=side,
        size=Decimal(size),
        price=Decimal(price),
        source_id=source_id,
        trade_timestamp_ms=timestamp,
        observed_at_ms=timestamp,
        market_slug="market",
    )


def _resolution() -> MarketResolutionEvent:
    return MarketResolutionEvent(
        condition_id="condition-market",
        market_slug="market",
        token_ids=("yes-market", "no-market"),
        winning_token_id="yes-market",
        winning_outcome=YES_OUTCOME,
        resolved_at_ms=2_000,
        source="test",
    )
