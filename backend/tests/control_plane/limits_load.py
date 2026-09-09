"""Bounded, synthetic paper-beta load rehearsal against disposable shared services.

Run with PYTHONPATH=backend/tests and POLYBOT_TEST_POSTGRES_URL /
POLYBOT_TEST_REDIS_URL. This creates accounts/history only in the named *_test DB.
External market traffic is deterministic; no vendor capacity claim is made.
"""

import asyncio
import json
import os
import resource
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from alembic import command
from alembic.config import Config
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.node_based.bot import NodeBasedBot
from api.events.contracts import ChartSampleEvent, ChartSamplePayload
from api.events.contracts.payloads.chart import (
    EquityChartPointPayload,
    MarketChartPointPayload,
)
from api.events.pagination import DEFAULT_EVENT_PAGE_LIMIT
from api.events.store import EventStore
from api.events.writer import RunEventWriter
from api.http.sse.subscription import RunSubscription
from api.limits.policy import PAPER_BETA
from api.limits.redis.request_budgets import RequestRateLimiter
from api.limits.redis.stream_admission import OpenStreamAdmission
from api.runs.status import RunStatus
from api.runs.store import RunStore
from conftest import (
    DummyBooks,
    DummyBroker,
    DummyMarkets,
    DummyPositions,
    DummyWalletActivity,
)
from polybot.framework.clock import system_now_ms, system_now_utc
from polybot.framework.context import BotContext
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.performance.contracts.valuation_status import ValuationStatus

from control_plane.disposable_services import (
    disposable_postgres_url,
    disposable_redis_url,
)
from control_plane.graph_fixtures import threshold_buy_graph
from control_plane.limits_fixtures import (
    account_bot,
    claim_run,
    queue_run,
    resource_services,
)
from control_plane.service_config import TEST_POSTGRES_URL_ENV, TEST_REDIS_URL_ENV

REHEARSAL_SECONDS = 15
BOOK_TICK_SECONDS = 0.05
DURABLE_TICK_SECONDS = 0.25
READ_TICK_SECONDS = 2.0
MAX_P95_IO_SECONDS = 0.25
MAX_P95_LOOP_LAG_SECONDS = 0.1


def main():
    postgres = disposable_postgres_url(
        os.environ[TEST_POSTGRES_URL_ENV]
    ).render_as_string(hide_password=False)
    redis = disposable_redis_url(os.environ[TEST_REDIS_URL_ENV])
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres)
    command.upgrade(config, "head")
    asyncio.run(rehearse((postgres, redis)))


async def rehearse(settings):
    async with resource_services(settings) as (sessions, redis):
        runs = []
        for _ in range(PAPER_BETA.global_active_runs):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            run = await claim_run(sessions, run)
            async with sessions() as session:
                await RunStore(session).mark_running(run.id)
            runs.append(run)
        io_latencies, loop_lags = [], []
        counters = {
            "books": 0,
            "writes": 0,
            "reads": 0,
            "stream_frames": 0,
            "requests": 0,
        }
        writer = RunEventWriter(sessions, redis)
        deadline = perf_counter() + REHEARSAL_SECONDS
        points = tuple(
            MarketChartPointPayload(
                token_id=f"token-{i}",
                label=f"Outcome {i}",
                value=Decimal("0.5"),
                status=ValuationStatus.FRESH,
                markers=(),
            )
            for i in range(PAPER_BETA.tracked_markets_per_run * 2)
        )

        async def books(run):
            bot = NodeBasedBot(NodeGraph.model_validate(threshold_buy_graph()))
            context = BotContext(
                config=run.config.to_bot_config(),
                broker=DummyBroker([]),
                markets=DummyMarkets(),
                books=DummyBooks(),
                positions=DummyPositions(),
                wallet_activity=DummyWalletActivity(),
            )
            await bot.on_start(context)
            book = BookSnapshot(
                token_id="fixture",
                bids=(BookLevel(Decimal("0.8"), Decimal(10)),),
                asks=(BookLevel(Decimal("0.9"), Decimal(10)),),
                received_at_ms=system_now_ms(),
            )
            while perf_counter() < deadline:
                for point in points:
                    await bot.on_book(
                        context,
                        replace(
                            book,
                            token_id=point.token_id,
                            received_at_ms=system_now_ms(),
                        ),
                    )
                    counters["books"] += 1
                before = perf_counter()
                await asyncio.sleep(BOOK_TICK_SECONDS)
                loop_lags.append(event_loop_lag_seconds(before))
            await bot.on_stop(context)

        async def writes(run):
            while perf_counter() < deadline:
                started = perf_counter()
                await writer.append(
                    ChartSampleEvent(
                        run_id=run.id,
                        occurred_at=system_now_utc(),
                        payload=ChartSamplePayload(
                            sampled_at_ms=system_now_ms(),
                            markets=points,
                            equity=EquityChartPointPayload(
                                value=Decimal(1000), status=ValuationStatus.FRESH
                            ),
                        ),
                    )
                )
                io_latencies.append(perf_counter() - started)
                counters["writes"] += 1
                await asyncio.sleep(DURABLE_TICK_SECONDS)

        async def reader(run):
            owner = uuid4()
            limiter = RequestRateLimiter(redis, owner)
            lease = await OpenStreamAdmission(redis, owner).acquire_stream()
            try:
                async with RunSubscription(redis, run.id) as subscription:
                    next_read = 0
                    while perf_counter() < deadline:
                        if perf_counter() >= next_read:
                            started = perf_counter()
                            await limiter.consume_request_budget(expensive=False)
                            async with sessions() as session:
                                await EventStore(session).read_page(
                                    run.id,
                                    before_event_id=None,
                                    limit=DEFAULT_EVENT_PAGE_LIMIT,
                                )
                            io_latencies.append(perf_counter() - started)
                            counters["reads"] += 1
                            counters["requests"] += 1
                            next_read = perf_counter() + READ_TICK_SECONDS
                        frame = await subscription.get_message(
                            ignore_subscribe_messages=True, timeout=0.1
                        )
                        if frame is not None:
                            counters["stream_frames"] += 1
            finally:
                await lease.release()

        try:
            async with asyncio.timeout(REHEARSAL_SECONDS + 10):
                await asyncio.gather(
                    *(books(run) for run in runs),
                    *(writes(run) for run in runs),
                    *(
                        reader(runs[index % len(runs)])
                        for index in range(PAPER_BETA.global_open_streams)
                    ),
                )
        finally:
            for run in runs:
                async with sessions() as session:
                    store = RunStore(session)
                    await store.begin_stopping(run.id)
                    await store.finish(
                        run.id, status=RunStatus.STOPPED, now=system_now_utc()
                    )
        io_p95 = percentile_95(io_latencies)
        lag_p95 = percentile_95(loop_lags)
        result = {
            "policy": PAPER_BETA.model_dump(),
            "duration_seconds": REHEARSAL_SECONDS,
            **counters,
            "io_p95_ms": round(io_p95 * 1000, 2),
            "loop_lag_p95_ms": round(lag_p95 * 1000, 2),
            "process_max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "passed": io_p95 < MAX_P95_IO_SECONDS
            and lag_p95 < MAX_P95_LOOP_LAG_SECONDS,
        }
        print(json.dumps(result, indent=2))
        if not result["passed"]:
            raise RuntimeError("bounded paper-beta load acceptance failed")


def event_loop_lag_seconds(before: float) -> float:
    return max(0, perf_counter() - before - BOOK_TICK_SECONDS)


def percentile_95(values: list[float]) -> float:
    return sorted(values)[int(len(values) * 0.95)]


if __name__ == "__main__":
    main()
