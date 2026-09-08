"""Paper-run launch, read, and stop endpoints."""

from uuid import UUID

from fastapi import APIRouter
from polybot.framework.clock import system_now_utc
from sqlalchemy.ext.asyncio import AsyncSession

from api.events.store import EventStore
from api.events.writer import publish_durable_wake
from api.http.dependencies import (
    RedisDependency,
    SessionFactoryDependency,
)
from api.http.lifecycle import ApiRunLifecycle
from api.http.responses import NOT_FOUND_RESPONSE
from api.http.routes.paths import (
    LIST_RUNS_OPERATION_ID,
    READ_RUN_OPERATION_ID,
    RUN_PATH,
    RUN_STOP_PATH,
    RUNS_PATH,
    STOP_RUN_OPERATION_ID,
)
from api.http.routes.run_lookup import (
    raise_run_not_found,
    require_run,
)
from api.runs.contracts import RunRead
from api.runs.store import RunStore

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
        return await _with_event_summaries(session, runs)


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
        return (await _with_event_summaries(session, (run,)))[0]


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
        run = (await _with_event_summaries(session, (run,)))[0]
    if terminal_event_id is not None:
        await publish_durable_wake(redis, run_id, terminal_event_id)
    return run


async def _with_event_summaries(
    session: AsyncSession,
    runs: tuple[RunRead, ...],
) -> tuple[RunRead, ...]:
    run_ids = tuple(run.id for run in runs)
    event_store = EventStore(session)
    latest_chart_samples_by_run = await event_store.latest_chart_samples(run_ids)
    latest_run_failures_by_run = await event_store.latest_run_failures(run_ids)
    summaries: list[RunRead] = []
    for run in runs:
        sample = latest_chart_samples_by_run.get(run.id)
        failure = latest_run_failures_by_run.get(run.id)
        summaries.append(
            run.with_event_summary(
                latest_equity=None if sample is None else sample.payload.equity.value,
                equity_status=None if sample is None else sample.payload.equity.status,
                latest_runtime_failure=None
                if failure is None
                else failure.payload.error,
            )
        )
    return tuple(summaries)
