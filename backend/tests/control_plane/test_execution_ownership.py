"""Real database ownership gates around paper fills and resolution settlement."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from api.events.store import EventStore
from api.events.writer import RunEventWriter
from api.execution.worker.fill_ownership import FillOwnership
from api.execution.worker.lifecycle import RunLifecycleCoordinator
from api.runs.failures import ExecutionOwnershipLost, RunSnapshotError
from api.runs.lease import ExecutionLease
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from polybot.cli.followed_wallets.tracker import FollowedWalletTracker
from polybot.cli.resolution.settlement import ResolutionSettlementService
from polybot.cli.tracked_markets import MarketInterest, TrackedMarketRegistry
from polybot.execution.paper import PaperBroker
from polybot.framework.clock import system_now_utc
from polybot.framework.config.models import BotConfig
from polybot.framework.events import OrderRequest, OrderStatus, Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.markets import Market, MarketOutcome
from sqlalchemy import update

from control_plane.limits_fixtures import account_bot, queue_run, resource_services
from control_plane.limits_fixtures import limits_services as limits_services


@pytest.mark.parametrize("ownership_loss", (None, "expired", "wrong_token", "terminal"))
def test_host_lease_fences_real_fill_and_settlement(limits_services, ownership_loss):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                claimed = await RunStore(session).claim(run.id, now=system_now_utc())
            scope = FillOwnership(
                run.id, sessions, ExecutionLease(claimed.execution_token)
            ).scope
            market = Market(
                condition_id="condition",
                slug="market",
                question="Will it happen?",
                minimum_tick_size=Decimal("0.01"),
                minimum_order_size=Decimal("1"),
                neg_risk=False,
                fee_rate=Decimal("0"),
                outcomes=(MarketOutcome("Yes", "123"), MarketOutcome("No", "456")),
                active=True,
                closed=False,
                order_book_enabled=True,
                accepting_orders=True,
            )
            book = BookSnapshot(
                token_id=market.token_ids[0],
                condition_id=market.condition_id,
                market_slug=market.slug,
                received_at_ms=1000,
                bids=(),
                asks=(BookLevel(price=Decimal("0.4"), size=Decimal("10")),),
            )
            paper = PaperBroker(
                BotConfig(
                    name="ownership", paper_latency_ms=0, paper_latency_jitter_ms=0
                ),
                AsyncMock(latest=AsyncMock(return_value=book)),
                AsyncMock(find_by_slug=AsyncMock(return_value=market)),
                now_ms_fn=lambda: 1000,
                execution_scope=scope,
            )
            order = OrderRequest(
                token_id=book.token_id,
                side=Side.BUY,
                price=Decimal("0.4"),
                size=Decimal("1"),
                market_slug=market.slug,
            )
            initial = paper.snapshot()
            assert (await paper.submit(order)).status is OrderStatus.FILLED
            assert paper.snapshot() != initial
            registry = TrackedMarketRegistry()
            registry.add(market, MarketInterest.CONFIGURED)
            wallets = FollowedWalletTracker()
            runner = AsyncMock()
            service = ResolutionSettlementService(
                runner,
                registry=registry,
                followed_wallets=wallets,
                paper_broker=paper,
                observer=None,
                execution_scope=scope,
            )
            event = MarketResolutionEvent(
                condition_id=market.condition_id,
                market_slug=market.slug,
                token_ids=market.token_ids,
                winning_token_id=book.token_id,
                winning_outcome=market.outcomes[0].label,
                resolved_at_ms=1000,
                source="fixture",
            )
            if ownership_loss is None:
                filled = paper.snapshot()
                assert await service.apply(event) is not None
                assert paper.snapshot() != filled
                assert not registry.entries
                runner.dispatch_market_resolution.assert_awaited_once_with(event)
                return
            async with sessions() as session:
                if ownership_loss == "terminal":
                    assert await RunStore(session).finish(
                        run.id, status=RunStatus.INTERRUPTED, now=system_now_utc()
                    )
                    row = await session.get(RunRow, run.id)
                    assert row.execution_token == claimed.execution_token
                    assert row.heartbeat_at == claimed.heartbeat_at
                else:
                    changes = (
                        {"execution_token": uuid4()}
                        if ownership_loss == "wrong_token"
                        else {
                            "heartbeat_at": system_now_utc()
                            - timedelta(seconds=DEFAULT_LEASE_SECONDS * 2)
                        }
                    )
                    await session.execute(
                        update(RunRow).where(RunRow.id == run.id).values(**changes)
                    )
                    await session.commit()
            before = paper.snapshot(), wallets.snapshot(), registry.entries
            with pytest.raises(ExecutionOwnershipLost):
                await paper.submit(order)
            with pytest.raises(ExecutionOwnershipLost):
                await service.apply(event)
            assert (paper.snapshot(), wallets.snapshot(), registry.entries) == before
            runner.dispatch_market_resolution.assert_not_awaited()

    asyncio.run(scenario())


def test_corrupted_claim_snapshot_fails_once_and_releases_queue(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                coordinator = RunLifecycleCoordinator(
                    RunStore(session), sessions, RunEventWriter(sessions, redis)
                )
                with patch.object(
                    RunStore,
                    "_read_row",
                    side_effect=RunSnapshotError("fixture corrupt revision"),
                ):
                    await coordinator.execute(run.id)
                    await coordinator.execute(run.id)
            async with sessions() as session:
                stored = await RunStore(session).read(run.id)
                assert stored.status is RunStatus.FAILED
                assert "RunSnapshotError" in stored.failure_detail
                assert len(await EventStore(session).read(run.id)) == 1
            assert await queue_run(sessions, bot)

    asyncio.run(scenario())
