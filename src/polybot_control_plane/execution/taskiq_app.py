"""Taskiq broker and the thin run-launch adapter."""

import os
from uuid import UUID

from taskiq_redis import RedisStreamBroker
from polybot_control_plane.execution.worker import execute_run


REDIS_URL = os.getenv("POLYBOT_REDIS_URL", "redis://localhost:6379/0")
broker = RedisStreamBroker(REDIS_URL)


@broker.task
async def execute_run_task(run_id: str) -> None:
    await execute_run(UUID(run_id))


class TaskiqRunLauncher:
    async def launch(self, run_id: UUID) -> None:
        await execute_run_task.kiq(str(run_id))
