"""Owned database and Redis lifecycle for one Taskiq delivery."""

import asyncio

from redis.asyncio import Redis

from api.deployment.settings import StartupSettings
from api.events.writer import RunEventWriter
from api.limits.admission import RunAdmission
from api.runs.store import RunStore

from .database import create_worker_database
from .lifecycle import RunLifecycleCoordinator


async def drain_queued_runs_with_worker_resources() -> None:
    settings = await asyncio.to_thread(StartupSettings.from_env)
    engine, session_factory = create_worker_database(
        settings.database_url.get_secret_value()
    )
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    event_writer = RunEventWriter(session_factory, redis)
    try:
        # Taskiq delivers a wake hint; PostgreSQL chooses the next fair queued run.
        while True:
            async with session_factory() as selection_session:
                eligible_run_id = await RunAdmission(selection_session).next_eligible_queued_run_id()
                await selection_session.commit()
            if eligible_run_id is None:
                return
            async with session_factory() as session:
                await RunLifecycleCoordinator(
                    RunStore(session),
                    session_factory,
                    event_writer,
                    heartbeat_seconds=settings.heartbeat_seconds,
                ).execute(eligible_run_id)
    finally:
        try:
            await redis.aclose()
        finally:
            await engine.dispose()
