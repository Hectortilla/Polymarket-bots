"""Owned database and Redis lifecycle for one Taskiq delivery."""

import asyncio
from uuid import UUID

from redis.asyncio import Redis

from api.deployment.settings import StartupSettings
from api.events.writer import RunEventWriter
from api.runs.store import RunStore

from .database import create_worker_database
from .lifecycle import RunLifecycleCoordinator


async def run_with_worker_resources(run_id: UUID) -> None:
    settings = await asyncio.to_thread(StartupSettings.from_env)
    engine, session_factory = create_worker_database(
        settings.database_url.get_secret_value()
    )
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    event_writer = RunEventWriter(session_factory, redis)
    try:
        async with session_factory() as session:
            await RunLifecycleCoordinator(
                RunStore(session),
                session_factory,
                event_writer,
                heartbeat_seconds=settings.heartbeat_seconds,
            ).execute(run_id)
    finally:
        try:
            await redis.aclose()
        finally:
            await engine.dispose()
