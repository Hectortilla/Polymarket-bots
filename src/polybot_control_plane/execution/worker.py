"""Taskiq worker entrypoint for one durable paper run."""

import asyncio
import os
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from polybot.framework.clock import system_now_utc
from polybot.runtime import run_bot
from polybot_control_plane.events.observer import WebRuntimeObserver
from polybot_control_plane.events.store import EventStore
from polybot_control_plane.catalog.definitions import CATALOG
from polybot_control_plane.runs.status import RunStatus
from polybot_control_plane.runs.store import RunStore


DATABASE_URL_ENV = "POLYBOT_DATABASE_URL"
MAX_FAILURE_DETAIL_LENGTH = 500
WORKER_POLL_INTERVAL_SECONDS = 5


def _database_url() -> str:
    return os.environ[DATABASE_URL_ENV].replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )


async def execute_run(run_id: UUID) -> None:
    engine = create_async_engine(_database_url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        store = RunStore(session)
        run = await store.claim(run_id, now=system_now_utc())
        if run is None:
            return
        try:
            entry = CATALOG[run.definition_id]
            if entry.version != run.definition_version:
                raise RuntimeError("catalog definition version is no longer available")
            bot_config = run.config.to_bot_config()
            await store.set_status(run_id, RunStatus.RUNNING)
            observer = WebRuntimeObserver(run_id, EventStore(session))
            bot_task = asyncio.create_task(
                run_bot(entry.create_bot(bot_config), bot_config, observer=observer)
            )
            monitor_task = asyncio.create_task(
                _monitor_run(run_id, bot_task, session_factory)
            )
            stop_requested = False
            try:
                await bot_task
            except asyncio.CancelledError:
                if not monitor_task.done():
                    stop_requested = await monitor_task
                else:
                    stop_requested = monitor_task.result()
                await store.finish(
                    run_id,
                    status=RunStatus.STOPPED if stop_requested else RunStatus.INTERRUPTED,
                    now=system_now_utc(),
                )
                if not stop_requested:
                    raise
            finally:
                monitor_task.cancel()
                await asyncio.gather(monitor_task, return_exceptions=True)
        except asyncio.CancelledError:
            await store.finish(run_id, status=RunStatus.INTERRUPTED, now=system_now_utc())
            raise
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"[:MAX_FAILURE_DETAIL_LENGTH]
            await store.finish(run_id, status=RunStatus.FAILED, now=system_now_utc(), failure_detail=detail)
        else:
            await store.finish(run_id, status=RunStatus.STOPPED, now=system_now_utc())
    await engine.dispose()


async def _monitor_run(
    run_id: UUID,
    bot_task: asyncio.Task[None],
    session_factory: async_sessionmaker[AsyncSession],
) -> bool:
    while not bot_task.done():
        await asyncio.sleep(WORKER_POLL_INTERVAL_SECONDS)
        async with session_factory() as session:
            status = await RunStore(session).status(run_id)
            if status is None:
                return False
            if status is RunStatus.STOP_REQUESTED:
                await RunStore(session).set_status(run_id, RunStatus.STOPPING)
                bot_task.cancel()
                return True
            await RunStore(session).heartbeat(run_id, now=system_now_utc())
    return False
