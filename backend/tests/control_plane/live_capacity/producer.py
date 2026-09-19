"""Synthetic accepted books through the real observer and worker live service."""

import asyncio
from decimal import Decimal
from time import monotonic
from uuid import UUID

from api.events.live.connections import LiveConnections
from api.events.live.policy import LIVE_MAX_IN_FLIGHT_PER_SHARD
from api.events.live.service import WorkerLiveTelemetry
from api.events.observer import WebRuntimeObserver
from api.events.terminal_wakes import TerminalWakePublisher
from api.events.writer import RunEventWriter
from api.execution.worker.database import create_worker_database
from api.io_policy import REDIS_CONTROL_POOL_SIZE, REDIS_SOCKET_OPTIONS
from api.runs.models import RunRow
from api.runs.lease import ExecutionLease
from api.runs.status import RunStatus
from api.runs.store import RunStore
from polybot.cli.observability.events import (
    DispatchCompleted,
    FillCompleted,
    PortfolioBookBootstrap,
    PortfolioPositionSnapshot,
    PortfolioSnapshot,
    StreamHealth,
)
from polybot.cli.streams.contracts import WalletStreamEvent
from polybot.cli.streams.kinds import StreamKind
from polybot.dashboard.contracts import CHART_SAMPLE_INTERVAL_SECONDS
from polybot.framework.clock import system_now_ms, system_now_utc
from polybot.framework.config.models import BotConfig
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import FillEvent, OrderRequest, OrderStatus, Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from redis.asyncio import Redis
from sqlalchemy import update

from control_plane.live_capacity.measurements import Measurements


class IsolatedDurableSink:
    """Declared isolation: preserve observer admission/cadence, omit chart SQL."""

    def __init__(self, measurements):
        self.measurements = measurements

    async def append(self, event):
        self.measurements.add("isolated_durable_events")
        return event


def run_producer(settings, rows, tokens, mode, stop, report, bursts):
    asyncio.run(produce(settings, rows, tokens, mode, stop, report, bursts))


async def produce(settings, rows, tokens, mode, stop, report, bursts):
    engine, sessions = create_worker_database(settings.database_url.get_secret_value())
    clients = LiveConnections(settings)
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(),
        max_connections=REDIS_CONTROL_POOL_SIZE,
        **REDIS_SOCKET_OPTIONS,
    )
    measurements = Measurements()
    measurements.instrument_sql(engine)
    live = WorkerLiveTelemetry(
        sessions, clients.router, clients.clients, lease_seconds=settings.lease_seconds
    )
    measurements.instrument_live(live.publisher)
    observers = []
    active = {}
    writer = RunEventWriter(sessions, redis)
    wakes = TerminalWakePublisher(sessions, redis)
    await wakes.start()
    await live.start()
    monitor = None
    try:
        for run_id, token in rows:
            run_id, token = UUID(run_id), UUID(token)
            sink = (
                writer.for_execution(token, settings.lease_seconds)
                if mode == "integrated"
                else IsolatedDurableSink(measurements)
            )
            observer = WebRuntimeObserver(
                run_id, sink, live_telemetry=live.for_execution(run_id, token)
            )
            await observer.start(BotConfig(name="capacity", event_max_age_ms=5000))
            observers.append(observer)
            active[run_id] = (token, observer)
        if mode == "integrated":
            monitor = asyncio.create_task(
                monitor_owned_runs(sessions, active, settings, measurements)
            )
        next_heartbeat = next_report = 0
        tick = 0
        while not stop.is_set():
            if monitor is not None and monitor.done():
                await monitor
            started = monotonic()
            now = system_now_ms()
            for _, observer in active.values():
                for index in range(tokens):
                    observer.emit(
                        PortfolioBookBootstrap(
                            BookSnapshot(
                                token_id=synthetic_token_id(index),
                                bids=(BookLevel(Decimal("0.49"), Decimal(1000)),),
                                asks=(BookLevel(Decimal("0.51"), Decimal(1000)),),
                                received_at_ms=now,
                            ),
                            occurred_at_monotonic_seconds=started,
                        )
                    )
                observer.emit(StreamHealth(0, 0, 0))
                if bursts and tick % 4 == 0:
                    for offset in range(10):
                        emit_annotation_burst(
                            observer, (tick // 4) * 10 + offset, now, started
                        )
            tick += 1
            if mode == "isolated" and started >= next_heartbeat:
                # Isolated mode deliberately substitutes execution monitoring.
                async with sessions() as session:
                    ids = list(active)
                    for offset in range(0, len(ids), 500):
                        await session.execute(
                            update(RunRow)
                            .where(RunRow.id.in_(ids[offset : offset + 500]))
                            .values(heartbeat_at=system_now_utc())
                        )
                    await session.commit()
                next_heartbeat = started + settings.heartbeat_seconds
            if started >= next_report:
                live.publisher.measure_slots()
                current = live.metrics.snapshot()
                measurements.observe("pending_snapshots", current.get("pending", 0))
                measurements.observe("pending_health", current.get("pending_health", 0))
                measurements.observe("inflight", current.get("inflight", 0))
                if (
                    current.get("pending", 0) > len(rows)
                    or current.get("pending_health", 0) > len(rows)
                    or current.get("inflight", 0)
                    > len(clients.clients) * LIVE_MAX_IN_FLIGHT_PER_SHARD
                ):
                    measurements.add("publisher_bound_violations")
                if any(
                    len(o._projection.charts.chart_sample_epoch_seconds)
                    for o in observers
                    if o._projection is not None
                ):
                    measurements.add("retained_history_violations")
                await measurements.write(
                    report,
                    live.metrics.snapshot(),
                    observer_tasks=len(observers) * 2,
                    retained_chart_points=sum(
                        len(o._projection.charts.chart_sample_epoch_seconds)
                        for o in observers
                        if o._projection is not None
                    ),
                    pending_durable=sum(o._pending.qsize() for o in observers),
                )
                next_report = started + 2
            await asyncio.sleep(
                max(0, CHART_SAMPLE_INTERVAL_SECONDS - (monotonic() - started))
            )
            measurements.observe(
                "loop_lag_seconds",
                max(0, monotonic() - started - CHART_SAMPLE_INTERVAL_SECONDS),
            )
    finally:
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        await asyncio.gather(*(observer.stop() for observer in observers))
        await live.close()
        await wakes.close()
        await measurements.write(report, live.metrics.snapshot(), clean_shutdown=True)
        await clients.close()
        await redis.aclose()
        await engine.dispose()


async def monitor_owned_runs(sessions, active, settings, measurements):
    while True:
        started = monotonic()
        for run_id, (token, observer) in tuple(active.items()):
            if not await maintain_owned_run(
                sessions,
                run_id,
                token,
                observer,
                settings.lease_seconds,
                measurements,
            ):
                active.pop(run_id)
        await asyncio.sleep(
            max(0, settings.heartbeat_seconds - (monotonic() - started))
        )


async def maintain_owned_run(
    sessions, run_id, token, observer, lease_seconds, measurements
):
    async with sessions() as session:
        owned = RunStore(session).owned_by(ExecutionLease(token, lease_seconds))
        if await owned.status(run_id) is RunStatus.STOP_REQUESTED:
            if not await owned.begin_stopping(run_id):
                raise RuntimeError("capacity stop lost execution ownership")
            await observer.stop()
            if not await owned.finish(
                run_id, status=RunStatus.STOPPED, now=system_now_utc()
            ):
                raise RuntimeError(
                    "capacity terminal transition lost execution ownership"
                )
            measurements.add("owned_stops")
            return False
        if not await owned.heartbeat(run_id, now=system_now_utc()):
            raise RuntimeError("capacity heartbeat lost execution ownership")
        measurements.add("owned_heartbeats")
        return True


def emit_annotation_burst(observer, index, now, started):
    token = synthetic_token_id(0)
    request = OrderRequest(
        token_id=token, side=Side.BUY, price=Decimal("0.5"), size=Decimal(1)
    )
    fill = FillEvent(
        order_id=str(index),
        token_id=token,
        side=Side.BUY,
        status=OrderStatus.FILLED,
        requested_size=Decimal(1),
        filled_size=Decimal(1),
        average_price=Decimal("0.5"),
        fee_usdc=Decimal(0),
        received_at_ms=now,
    )
    portfolio = PortfolioSnapshot(
        Decimal(1000) - Decimal(index + 1) / 2,
        Decimal(0),
        (PortfolioPositionSnapshot(token, Decimal(index + 1), Decimal("0.5")),),
    )
    observer.emit(FillCompleted(request, fill, portfolio, 1, started))
    trade = WalletTradeEvent(
        wallet="0x" + "a" * 40,
        condition_id="capacity",
        token_id=token,
        side=Side.BUY,
        size=Decimal(1),
        price=Decimal("0.5"),
        source_id=str(index),
        trade_timestamp_ms=now,
        observed_at_ms=now,
    )
    observer.emit(
        DispatchCompleted(
            WalletStreamEvent(StreamKind.WALLET, trade),
            DispatchOutcome.accepted_event(),
            started,
        )
    )


def synthetic_token_id(index):
    return str(10**76 + index)
