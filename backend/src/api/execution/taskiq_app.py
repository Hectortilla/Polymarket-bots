"""Taskiq broker and the thin run-launch adapter."""

from uuid import UUID

from taskiq_redis import RedisStreamBroker

from api.execution.config import configured_redis_url
from api.execution.worker import execute_run


broker = RedisStreamBroker(
    configured_redis_url(),
    consumer_id="0-0",
)


@broker.task
async def execute_run_task(run_id: str) -> None:
    await execute_run(UUID(run_id))


class TaskiqRunLauncher:
    async def launch(self, run_id: UUID) -> None:
        await execute_run_task.kiq(str(run_id))
