"""Bounded, best-effort web telemetry; durable admission owns marker consumption."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from polybot.cli.observability.events import RuntimeEvent, StreamHealth
from polybot.dashboard.contracts import CHART_SAMPLE_INTERVAL_SECONDS, DashboardSample
from polybot.dashboard.projection import DashboardProjection
from polybot.framework.clock import system_now_ms, system_now_utc
from polybot.framework.config.models import BotConfig

from api.events.contracts import ChartSampleEvent, DurableEvent, StreamHealthEvent
from api.events.contracts.payloads.lifecycle import FeedObservation
from api.events.live.service import RunLiveTelemetry
from api.execution.policy import RUNTIME_CLEANUP_SECONDS
from api.operations.observations.contracts import FailureObservation, Observation
from api.operations.observations.sink import OPERATION_LOG

from .projection import project_runtime_event_to_durable
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
        live_telemetry: RunLiveTelemetry,
        max_pending_events: int = MAX_PENDING_EVENTS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now_ms: Callable[[], int] = system_now_ms,
        now_utc: Callable[[], datetime] = system_now_utc,
    ) -> None:
        self._run_id = run_id
        self._event_writer = event_writer
        self._live_telemetry = live_telemetry
        self._pending: asyncio.Queue[DurableEvent | None] = asyncio.Queue(
            maxsize=max_pending_events
        )
        self._pending_sample: tuple[DashboardSample, ChartSampleEvent] | None = None
        self._writer: asyncio.Task[None] | None = None
        self._projection: DashboardProjection | None = None
        self._cadence: asyncio.Task[None] | None = None
        self._shutdown: asyncio.Task[None] | None = None
        self._health_observation: FeedObservation | None = None
        self._sleep, self._now_ms, self._now_utc = sleep, now_ms, now_utc

    async def start(self, config: BotConfig) -> None:
        if self._shutdown is not None:
            raise RuntimeError("observer has already stopped")
        self._projection = DashboardProjection.from_config(config, retain_history=False)
        self._writer = asyncio.create_task(self._write_events())
        self._cadence = asyncio.create_task(self._publish_dashboard())

    def emit(self, event: RuntimeEvent) -> None:
        if self._writer is None or self._shutdown is not None:
            return
        if self._projection is not None:
            change = self._projection.apply(event)
            if change.marker_overflow:
                self._failure()
        if isinstance(event, StreamHealth):
            self._health_observation = FeedObservation.from_observation(
                event, observed_at=self._now_utc()
            )
            return
        for projected in project_runtime_event_to_durable(self._run_id, event):
            self._enqueue(projected)

    async def stop(self) -> None:
        if self._shutdown is None:
            self._live_telemetry.close()
            self._shutdown = asyncio.create_task(self._stop())
        # Runtime cancellation and coordinator cleanup may both await this drain.
        await asyncio.shield(self._shutdown)

    async def _stop(self) -> None:
        try:
            if self._cadence is not None:
                self._cadence.cancel()
                results = await asyncio.gather(self._cadence, return_exceptions=True)
                if any(isinstance(result, Exception) for result in results):
                    self._failure()
                self._cadence = None
            if self._writer is not None:
                async with asyncio.timeout(RUNTIME_CLEANUP_SECONDS):
                    await self._drain()
        except Exception:
            self._failure()
        finally:
            if self._writer is not None:
                self._writer.cancel()
                await asyncio.gather(self._writer, return_exceptions=True)
                self._writer = None
            self._projection = None
            self._pending_sample = None
            while not self._pending.empty():
                self._pending.get_nowait()

    async def _drain(self) -> None:
        projection = self._projection
        if projection is not None:
            if self._pending_sample is not None:
                sample, event = self._pending_sample
                await self._pending.put(event)
                projection.acknowledge_sample(sample)
                self._pending_sample = None
            sample = projection.sample_durable(self._now_ms())
            await self._pending.put(
                ChartSampleEvent.from_sample(
                    self._run_id, sample, occurred_at=self._now_utc()
                )
            )
            projection.acknowledge_sample(sample)
        if self._health_observation is not None:
            await self._pending.put(
                StreamHealthEvent.from_observation(
                    self._run_id, self._health_observation
                )
            )
        await self._pending.put(None)
        await self._writer

    async def _publish_dashboard(self) -> None:
        tick = 0
        while True:
            await self._sleep(CHART_SAMPLE_INTERVAL_SECONDS)
            projection = self._projection
            if projection is None:
                return
            occurred_at = self._now_utc()
            if self._live_telemetry.watched():
                self._live_telemetry.publish(
                    projection.sample_current(self._now_ms()),
                    occurred_at=occurred_at,
                    health=self._health_observation,
                )
            tick += 1
            if tick % DURABLE_DASHBOARD_TICKS:
                continue
            if self._health_observation is not None:
                self._live_telemetry.record_health(self._health_observation)
            self._sample_durable(projection, occurred_at)

    def _sample_durable(
        self, projection: DashboardProjection, occurred_at: datetime
    ) -> None:
        # Keep exactly one failed sample, including its original timestamp. New
        # markers stay bounded in the projection until that sample is admitted.
        if self._pending_sample is not None:
            sample, event = self._pending_sample
            if not self._enqueue(event):
                return
            projection.acknowledge_sample(sample)
            self._pending_sample = None
        sample = projection.sample_durable(self._now_ms())
        event = ChartSampleEvent.from_sample(
            self._run_id, sample, occurred_at=occurred_at
        )
        if self._enqueue(event):
            projection.acknowledge_sample(sample)
        else:
            self._pending_sample = sample, event

    async def _write_events(self) -> None:
        while True:
            event = await self._pending.get()
            if event is None:
                return
            try:
                await self._event_writer.append(event)
            except Exception:
                self._failure()

    def _enqueue(self, event: DurableEvent) -> bool:
        try:
            self._pending.put_nowait(event)
        except asyncio.QueueFull:
            self._failure()
            return False
        return True

    @staticmethod
    def _failure() -> None:
        OPERATION_LOG.emit(FailureObservation(Observation.OBSERVER_FAILURE))
