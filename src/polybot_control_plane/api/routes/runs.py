"""Paper-run launch, read, and stop endpoints."""

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from polybot.framework.clock import system_now_utc
from polybot_control_plane.api.dependencies import (
    RedisDependency,
    SessionFactoryDependency,
)
from polybot_control_plane.api.lifecycle import ApiRunLifecycle
from polybot_control_plane.api.routes.paths import (
    LIST_RUNS_OPERATION_ID,
    READ_RUN_OPERATION_ID,
    RUN_PATH,
    RUN_STOP_PATH,
    RUNS_PATH,
    STOP_RUN_OPERATION_ID,
)
from polybot_control_plane.api.routes.run_lookup import (
    raise_run_not_found,
    require_run,
)
from polybot_control_plane.api.responses import NOT_FOUND_RESPONSE
from polybot_control_plane.events.contracts import ChartSampleEvent
from polybot_control_plane.events.store import EventStore
from polybot_control_plane.events.writer import publish_durable_wake
from polybot_control_plane.runs.contracts import RunRead
from polybot_control_plane.runs.store import RunStore


router = APIRouter()


@router.get(
    RUNS_PATH,
    response_model=list[RunRead],
    operation_id=LIST_RUNS_OPERATION_ID,
)
async def list_runs(
    session_factory: SessionFactoryDependency,
) -> tuple[RunRead, ...]:
    async with session_factory() as session:
        runs = await RunStore(session).list()
        return await _with_equity_summaries(session, runs)


@router.get(
    RUN_PATH,
    response_model=RunRead,
    operation_id=READ_RUN_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def read_run(
    run_id: UUID,
    session_factory: SessionFactoryDependency,
) -> RunRead:
    async with session_factory() as session:
        run = require_run(await RunStore(session).read(run_id))
        return (await _with_equity_summaries(session, (run,)))[0]


@router.post(
    RUN_STOP_PATH,
    response_model=RunRead,
    operation_id=STOP_RUN_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def stop_run(
    run_id: UUID,
    session_factory: SessionFactoryDependency,
    redis: RedisDependency,
) -> RunRead:
    now = system_now_utc()
    async with session_factory() as session:
        transition = await ApiRunLifecycle(session).request_stop(run_id, now=now)
        if transition is None:
            raise_run_not_found()
        run, terminal_event_id = transition
        run = (await _with_equity_summaries(session, (run,)))[0]
    if terminal_event_id is not None:
        await publish_durable_wake(redis, run_id, terminal_event_id)
    return run


async def _with_equity_summaries(
    session: AsyncSession,
    runs: tuple[RunRead, ...],
) -> tuple[RunRead, ...]:
    latest_chart_samples_by_run = await EventStore(session).latest_chart_samples(
        tuple(run.id for run in runs)
    )
    return tuple(
        _with_equity_summary(run, latest_chart_samples_by_run.get(run.id))
        for run in runs
    )


def _with_equity_summary(
    run: RunRead,
    sample: ChartSampleEvent | None,
) -> RunRead:
    if sample is None:
        return run
    return run.model_copy(
        update={
            "latest_equity": sample.payload.equity.value,
            "equity_status": sample.payload.equity.status,
        }
    )
