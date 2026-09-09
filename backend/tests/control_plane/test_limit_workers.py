"""Capacity survives worker processes, stop transitions and retained history."""

import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from decimal import Decimal
from multiprocessing import Manager
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import AsyncMock

import api.execution.worker.lifecycle as lifecycle
import api.execution.worker.runtime as worker_runtime
import polybot.runtime as runtime_module
import pytest
from api.events.kinds import EventKind
from api.events.pagination import DEFAULT_EVENT_PAGE_LIMIT
from api.events.store import EventStore
from api.events.writer import RunEventWriter
from api.limits.policy import PAPER_BETA
from api.limits.usage import AccountUsageReader
from api.runs.failures import RunFailureReason
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from polybot.execution.paper.portfolio import PaperPosition
from polybot.framework.base import BaseBot
from polybot.framework.clock import system_now_utc
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.polymarket.markets import Market, MarketOutcome
from polybot.polymarket.public_data.runtime import RuntimePublicData

from control_plane.limits_fixtures import (
    account_bot,
    claim_run,
    process_drain_queue,
    process_gated_queue_drain,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services


@pytest.mark.parametrize("process_count", [1, 3])
def test_worker_deliveries_drain_fifo_without_duplicate_execution(
    limits_services, process_count
):
    async def setup():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            _, other_bot = await account_bot(sessions)
            return [
                await queue_run(sessions, selected)
                for selected in (bot, bot, other_bot, other_bot)
            ]

    runs = asyncio.run(setup())
    with ProcessPoolExecutor(max_workers=process_count) as workers:
        results = list(
            workers.map(process_drain_queue, [limits_services] * process_count)
        )
    executed = [run_id for group in results for run_id in group]
    assert sorted(executed) == sorted(run.id for run in runs)
    if process_count == 1:
        assert executed == [run.id for run in runs]


def test_stopping_holds_capacity_until_terminal_commit(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            await claim_run(sessions, run)
            async with sessions() as session:
                store = RunStore(session)
                await store.mark_running(run.id)
                await store.request_stop(run.id, now=system_now_utc())
                assert (
                    await AccountUsageReader(session, user.id).usage()
                ).active_runs == 1
                await store.begin_stopping(run.id)
                assert (
                    await AccountUsageReader(session, user.id).usage()
                ).active_runs == 1
                await store.finish(
                    run.id, status=RunStatus.STOPPED, now=system_now_utc()
                )
                assert (
                    await AccountUsageReader(session, user.id).usage()
                ).active_runs == 0

    asyncio.run(scenario())


def test_elapsed_startup_expires_immediately(limits_services, monkeypatch):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            queued = await queue_run(sessions, bot)
            async with sessions() as session:
                store = RunStore(session)
                claimed = await store.claim(
                    queued.id,
                    now=system_now_utc()
                    - timedelta(seconds=PAPER_BETA.run_duration_seconds + 1),
                )
                monkeypatch.setattr(store, "claim", AsyncMock(return_value=claimed))

                runtime = AsyncMock(side_effect=AssertionError("expired run executed"))
                monkeypatch.setattr(lifecycle, "run_claimed_bot", runtime)
                await asyncio.wait_for(
                    lifecycle.RunLifecycleCoordinator(
                        store, sessions, RunEventWriter(sessions, redis)
                    ).execute(queued.id),
                    0.5,
                )
                run = await store.read(queued.id)
                assert run.status is RunStatus.STOPPED
                assert run.failure_detail == lifecycle.DURATION_EXPIRED_DETAIL
                runtime.assert_not_awaited()

    asyncio.run(scenario())


def test_owned_history_bound_preserves_old_active_and_queued_runs(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            _, other_bot = await account_bot(sessions)
            active = await queue_run(sessions, bot)
            await claim_run(sessions, active)
            queued = await queue_run(sessions, bot)
            await queue_run(sessions, other_bot)
            async with sessions() as session:
                now = system_now_utc()
                for index in range(PAPER_BETA.retained_runs + 5):
                    session.add(
                        RunRow(
                            bot_id=bot.id,
                            definition_id=bot.definition_id,
                            config=bot.config.model_dump(mode="json"),
                            status=RunStatus.STOPPED,
                            created_at=now + timedelta(seconds=index),
                            ended_at=now,
                        )
                    )
                await session.commit()
                visible = await RunStore(session).list_owned(user.id)
                assert len(visible) == PAPER_BETA.retained_runs + 2
                assert {active.id, queued.id} <= {run.id for run in visible}
                assert all(run.bot_id == bot.id for run in visible)
                assert [run.created_at for run in visible] == sorted(
                    (run.created_at for run in visible), reverse=True
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("position_discovery", [False, True])
def test_dynamic_runtime_market_cap_fails_and_closes_resources(
    limits_services, monkeypatch, position_discovery
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            stopped = asyncio.Event()
            markets = tuple(
                Market(
                    slug=f"dynamic-{i}",
                    condition_id=f"condition-{i}",
                    outcomes=(
                        MarketOutcome("Yes", f"yes-{i}"),
                        MarketOutcome("No", f"no-{i}"),
                    ),
                    question="Fixture",
                    minimum_tick_size=Decimal("0.01"),
                    minimum_order_size=Decimal(1),
                    neg_risk=False,
                    fee_rate=Decimal(0),
                )
                for i in range(PAPER_BETA.tracked_markets_per_run + 1)
            )

            class DynamicBot(BaseBot):
                async def current_stream_rules(self, ctx, now_ms):
                    return (
                        StreamRule(
                            StreamRelation.INDEPENDENT,
                            tuple(
                                m.slug
                                for m in (
                                    markets[:-1] if position_discovery else markets
                                )
                            ),
                        ),
                    )

                async def on_stop(self, ctx):
                    stopped.set()

            sources = SimpleNamespace(
                gamma=AsyncMock(),
                clob=AsyncMock(),
                market_stream=AsyncMock(),
                wallet_activity_client=AsyncMock(),
                position_client=AsyncMock(),
                close=AsyncMock(),
            )
            sources.gamma.find_many.side_effect = lambda slugs: tuple(
                next(m for m in markets if m.slug == slug) for slug in slugs
            )
            if position_discovery:
                create_runtime = runtime_module.create_runtime

                async def with_held_position(*args, **kwargs):
                    runtime = await create_runtime(*args, **kwargs)
                    market = markets[-1]
                    portfolio, settled, refs = runtime.paper_broker.snapshot()
                    position = PaperPosition(
                        market.token_ids[0], Decimal(1), Decimal("0.5")
                    )
                    cash, fees, positions = portfolio
                    positions[position.token_id] = position
                    portfolio = (cash, fees, positions)
                    refs[position.token_id] = (market.slug, market.condition_id)
                    runtime.paper_broker.restore((portfolio, settled, refs))
                    return runtime

                monkeypatch.setattr(
                    runtime_module, "create_runtime", with_held_position
                )
            monkeypatch.setattr(RuntimePublicData, "create", lambda: sources)
            monkeypatch.setattr(
                worker_runtime,
                "CATALOG",
                {
                    bot.definition_id: SimpleNamespace(
                        create_bot=lambda *args: DynamicBot()
                    )
                },
            )
            async with sessions() as session:
                await lifecycle.RunLifecycleCoordinator(
                    RunStore(session), sessions, RunEventWriter(sessions, redis)
                ).execute(run.id)
            async with sessions() as session:
                finished = await RunStore(session).read(run.id)
                assert finished.status is RunStatus.FAILED
                assert (
                    finished.failure_detail == RunFailureReason.TRACKED_MARKET_ALLOWANCE
                )
                assert (
                    await AccountUsageReader(session, user.id).usage()
                ).active_runs == 0
                page = await EventStore(session).read_page(
                    run.id, before_event_id=None, limit=DEFAULT_EVENT_PAGE_LIMIT
                )
                failures = [
                    event
                    for event in page.events
                    if event.kind is EventKind.RUN_FAILURE
                ]
                assert (
                    failures
                    and failures[0].payload.error
                    == RunFailureReason.TRACKED_MARKET_ALLOWANCE
                )
            assert stopped.is_set()
            sources.close.assert_awaited_once()

    asyncio.run(scenario())


def test_global_capacity_with_more_worker_processes_than_slots(limits_services):
    async def setup():
        async with resource_services(limits_services) as (sessions, redis):
            runs = []
            for _ in range(PAPER_BETA.global_active_runs + 2):
                _, bot = await account_bot(sessions)
                runs.append(await queue_run(sessions, bot))
            return runs

    runs = asyncio.run(setup())
    with Manager() as manager, ProcessPoolExecutor(max_workers=len(runs)) as workers:
        started, release = manager.list(), manager.Event()
        jobs = [
            workers.submit(process_gated_queue_drain, limits_services, started, release)
            for _ in runs
        ]
        try:
            deadline = monotonic() + 12
            while monotonic() < deadline:
                # Excess deliveries return only after observing the occupied global slots.
                if (
                    len(started) >= PAPER_BETA.global_active_runs
                    and sum(job.done() for job in jobs)
                    >= len(runs) - PAPER_BETA.global_active_runs
                ):
                    break
                sleep(0.01)
            assert len(started) == PAPER_BETA.global_active_runs
            assert (
                sum(job.done() for job in jobs)
                >= len(runs) - PAPER_BETA.global_active_runs
            )
        finally:
            release.set()
        for job in jobs:
            job.result(timeout=10)
        assert sorted(started) == sorted(run.id for run in runs)
