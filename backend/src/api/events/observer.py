"""Fail-open runtime observer for web-visible durable progress."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from polybot.cli.observability.events import (
    RuntimeEvent,
    StreamHealth,
)
from polybot.dashboard.contracts import (
    CHART_SAMPLE_INTERVAL_SECONDS,
    DashboardSample,
    WalletChartPoint,
)
from polybot.dashboard.projection import DashboardProjection
from polybot.framework.clock import system_now_ms, system_now_utc
from polybot.framework.config.models import BotConfig
from polybot.framework.events import Side

from api.events.contracts import (
    ChartSampleEvent,
    LiveStreamHealthEvent,
    StreamHealthEvent,
)
from api.operations.observations.contracts import FailureObservation, Observation
from api.operations.observations.sink import OPERATION_LOG

from .contracts import DurableEvent
from .projection import project_live_chart_events, project_runtime_event_to_durable
from .writer import RunEventWriter

MAX_PENDING_EVENTS = 256
DURABLE_DASHBOARD_INTERVAL_SECONDS = 1.0
DURABLE_DASHBOARD_TICKS = round(
    DURABLE_DASHBOARD_INTERVAL_SECONDS / CHART_SAMPLE_INTERVAL_SECONDS
)


class WebRuntimeObserver:
    def __init__(
        self,
        run_id: UUID,
        event_writer: RunEventWriter,
        *,
        max_pending_events: int = MAX_PENDING_EVENTS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now_ms: Callable[[], int] = system_now_ms,
        now_utc: Callable[[], datetime] = system_now_utc,
    ) -> None:
        self._run_id = run_id
        self._event_writer = event_writer
        self._health_writer = event_writer.health_writer()
        self._health_observed_at: datetime | None = None
        self._recorded_health_at: datetime | None = None
        self._pending: asyncio.Queue[DurableEvent | None] = asyncio.Queue(
            maxsize=max_pending_events
        )
        self._writer: asyncio.Task[None] | None = None
        self._latest_stream_health: StreamHealth | None = None
        self._projection: DashboardProjection | None = None
        self._cadence: asyncio.Task[None] | None = None
        self._sleep = sleep
        self._now_ms = now_ms
        self._now_utc = now_utc
        self._dirty_wallet_sources: set[str] = set()
        self._durable_markers: dict[str, list[Side]] = {}

    async def start(self, config: BotConfig) -> None:
        self._projection = DashboardProjection.from_config(config)
        self._writer = asyncio.create_task(self._write_events())
        self._cadence = asyncio.create_task(self._publish_dashboard())

    def emit(self, event: RuntimeEvent) -> None:
        if self._writer is None:
            return
        projection = self._projection
        if projection is not None:
            change = projection.apply(event)
            if change.wallet_event is not None:
                self._dirty_wallet_sources.add(change.wallet_event.source_key)
        if isinstance(event, StreamHealth):
            self._latest_stream_health = event
            self._health_observed_at = self._now_utc()
            return
        for projected in project_runtime_event_to_durable(self._run_id, event):
            self._enqueue(projected)

    async def stop(self) -> None:
        if self._writer is None:
            return
        if self._cadence is not None:
            self._cadence.cancel()
            await asyncio.gather(self._cadence, return_exceptions=True)
            self._cadence = None
        projection = self._projection
        if projection is not None:
            occurred_at = self._now_utc()
            await self._pending.put(
                ChartSampleEvent.from_sample(
                    self._run_id,
                    self._with_durable_markers(projection.sample(self._now_ms())),
                    occurred_at=occurred_at,
                )
            )
        if self._latest_stream_health is not None:
            await self._pending.put(
                StreamHealthEvent.from_observation(
                    self._run_id,
                    self._latest_stream_health,
                )
            )
            self._latest_stream_health = None
        # The sentinel is queued after every accepted event so graceful stop
        # drains committed progress and final health before terminal lifecycle.
        await self._pending.put(None)
        await self._writer
        self._writer = None
        self._projection = None

    async def _write_events(self) -> None:
        while True:
            event = await self._pending.get()
            if event is None:
                return
            try:
                await self._event_writer.append(event)
            except Exception:
                # Telemetry persistence failures must not change paper execution.
                OPERATION_LOG.emit(FailureObservation(Observation.OBSERVER_FAILURE))
                continue

    async def _publish_dashboard(self) -> None:
        tick = 0
        while True:
            await self._sleep(CHART_SAMPLE_INTERVAL_SECONDS)
            projection = self._projection
            if projection is None:
                return
            sample = projection.sample(self._now_ms())
            wallet_points = self._take_dirty_wallet_points(projection)
            occurred_at = self._now_utc()
            for event in project_live_chart_events(
                self._run_id,
                sample,
                wallet_points,
                occurred_at=occurred_at,
            ):
                try:
                    await self._event_writer.publish_live(event)
                except Exception:
                    continue
            self._remember_markers(sample)
            tick += 1
            if tick % DURABLE_DASHBOARD_TICKS:
                continue
            health = self._latest_stream_health
            if health is not None:
                await self._publish_stream_health(health, occurred_at)
            self._enqueue(
                ChartSampleEvent.from_sample(
                    self._run_id,
                    self._with_durable_markers(sample),
                    occurred_at=occurred_at,
                )
            )

    async def _publish_stream_health(
        self, health: StreamHealth, occurred_at: datetime
    ) -> None:
        # Dashboard ticks reuse a sample; only a new feed observation may
        # renew its stored lifetime. Capture its timestamp before awaiting I/O.
        health_observed_at = self._health_observed_at
        if health_observed_at != self._recorded_health_at:
            try:
                await self._health_writer.record(
                    LiveStreamHealthEvent.from_observation(
                        self._run_id,
                        health,
                        occurred_at=health_observed_at,
                    )
                )
                self._recorded_health_at = health_observed_at
            except Exception:
                OPERATION_LOG.emit(
                    FailureObservation(Observation.TELEMETRY_UNAVAILABLE)
                )
        try:
            await self._event_writer.publish_live(
                LiveStreamHealthEvent.from_observation(
                    self._run_id,
                    health,
                    occurred_at=occurred_at,
                )
            )
        except Exception:
            pass

    def _take_dirty_wallet_points(
        self,
        projection: DashboardProjection,
    ) -> tuple[WalletChartPoint, ...]:
        points = tuple(
            point
            for source_key in sorted(self._dirty_wallet_sources)
            if (point := projection.wallet_point(source_key)) is not None
        )
        self._dirty_wallet_sources.clear()
        return points

    def _enqueue(self, event: DurableEvent) -> None:
        try:
            self._pending.put_nowait(event)
        except asyncio.QueueFull:
            # Synchronous paper callbacks cannot wait for a saturated observer.
            OPERATION_LOG.emit(FailureObservation(Observation.OBSERVER_FAILURE))
            return

    def _remember_markers(self, sample: DashboardSample) -> None:
        for point in sample.markets:
            if point.markers:
                self._durable_markers.setdefault(point.token_id, []).extend(
                    point.markers
                )

    def _with_durable_markers(self, sample: DashboardSample) -> DashboardSample:
        durable_sample = replace(
            sample,
            markets=tuple(
                replace(
                    point,
                    markers=tuple(self._durable_markers.get(point.token_id, ())),
                )
                for point in sample.markets
            ),
        )
        self._durable_markers.clear()
        return durable_sample
