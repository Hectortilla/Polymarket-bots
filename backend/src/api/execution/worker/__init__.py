"""Taskiq delivery entrypoint that drains eligible durable paper runs."""

from uuid import UUID

from api.limits.admission import RunAdmission
from api.runs.store import RunStore

from .lifecycle import RunLifecycleCoordinator
from .resources import WorkerResources


async def execute_run(run_id: UUID, *, resources: WorkerResources) -> None:
    # The run ID remains a wake hint; PostgreSQL selects the next fair queued run.
    async with resources.delivery():
        while not resources.closing:
            async with resources.sessions() as selection_session:
                eligible_run_id = await RunAdmission(
                    selection_session
                ).next_eligible_queued_run_id()
                await selection_session.commit()
            if eligible_run_id is None or resources.closing:
                return
            async with resources.sessions() as session:
                await RunLifecycleCoordinator(
                    RunStore(session),
                    resources.sessions,
                    resources.event_writer,
                    live_telemetry=resources.live_telemetry,
                    heartbeat_seconds=resources.settings.heartbeat_seconds,
                    lease_seconds=resources.settings.lease_seconds,
                ).execute(eligible_run_id)
