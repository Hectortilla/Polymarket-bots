"""Capacity evidence must fail closed when workloads or ownership are missing."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from api.runs.models import RunRow
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.status import RunStatus
from api.runs.store import RunStore
from polybot.framework.clock import system_now_utc

from control_plane.limits_fixtures import (
    account_bot,
    claim_run,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services
from control_plane.live_capacity.checks import evaluate
from control_plane.live_capacity.measurements import Measurements
from control_plane.live_capacity.producer import maintain_owned_run


def test_capacity_gate_requires_every_viewer_and_no_unwatched_bytes():
    measurements = Measurements()
    measurements.add("live_frames", 1000)
    measurements.add("viewers_with_live", 1)
    workload = SimpleNamespace(
        producers=10,
        watched_percent=100,
        viewers_per_watched_run=3,
        hot_run_viewers=0,
        mode="isolated",
        faults=False,
        slow_viewers=0,
        duration_seconds=30,
        smoke=True,
    )
    report = {"role": "worker", "counts": {}, "telemetry": {"published_bytes": 100}}
    checks, passed = evaluate(measurements, [report], workload, [0], 0)
    assert not checks["watched_delivery"] and not passed
    measurements.counts["viewers_with_live"] = 30
    checks, _ = evaluate(measurements, [report], workload, [0], 0)
    assert checks["watched_delivery"]
    workload.watched_percent = 0
    checks, passed = evaluate(measurements, [report], workload, [0], None)
    assert not checks["no_viewer_snapshot_bytes"] and not passed


def test_integrated_capacity_uses_owned_heartbeat_and_stop(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, _):
            _, bot = await account_bot(sessions)
            run = await claim_run(sessions, await queue_run(sessions, bot))
            measurements = Measurements()
            stopped = []

            class Observer:
                async def stop(self):
                    stopped.append(True)

            observer = Observer()
            with pytest.raises(RuntimeError, match="heartbeat lost"):
                await maintain_owned_run(
                    sessions,
                    run.id,
                    uuid4(),
                    observer,
                    DEFAULT_LEASE_SECONDS,
                    measurements,
                )
            assert await maintain_owned_run(
                sessions,
                run.id,
                run.execution_token,
                observer,
                DEFAULT_LEASE_SECONDS,
                measurements,
            )
            async with sessions() as session:
                await RunStore(session).request_stop(run.id, now=system_now_utc())
            assert not await maintain_owned_run(
                sessions,
                run.id,
                run.execution_token,
                observer,
                DEFAULT_LEASE_SECONDS,
                measurements,
            )
            async with sessions() as session:
                assert (await session.get(RunRow, run.id)).status is RunStatus.STOPPED
            assert stopped == [True]
            assert measurements.counts["owned_stops"] == 1
            assert measurements.counts["owned_heartbeats"] == 1

    asyncio.run(scenario())
