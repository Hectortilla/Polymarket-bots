"""Owned database and Redis lifecycle for one Taskiq delivery."""

from uuid import UUID

from redis.asyncio import Redis

from api.events.writer import RunEventWriter
from api.execution.config import configured_redis_url
from api.runs.store import RunStore

from .database import create_worker_database
from .lifecycle import RunLifecycleCoordinator


async def run_with_worker_resources(run_id: UUID) -> None:
    engine, session_factory = create_worker_database()
    redis = Redis.from_url(configured_redis_url())
    event_writer = RunEventWriter(session_factory, redis)
    try:
        async with session_factory() as session:
            await RunLifecycleCoordinator(
                RunStore(session),
                session_factory,
                event_writer,
            ).execute(run_id)
    finally:
        await redis.aclose()
        await engine.dispose()
