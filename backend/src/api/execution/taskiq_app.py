"""Taskiq broker and the thin run-launch adapter."""

from uuid import UUID

from polybot.framework.timestamps import MILLISECONDS_PER_SECOND
from taskiq import TaskiqEvents
from taskiq_redis import RedisStreamBroker

from api.execution.config import configured_redis_url
from api.execution.policy import MAX_RETAINED_WAKE_HINTS, TASKIQ_READ_BLOCK_SECONDS
from api.execution.worker import execute_run
from api.io_policy import REDIS_SOCKET_OPTIONS
from api.operations.worker import start_worker_presence, stop_worker_presence

broker = RedisStreamBroker(
    configured_redis_url(),
    consumer_id="0-0",
    maxlen=MAX_RETAINED_WAKE_HINTS,
    **REDIS_SOCKET_OPTIONS,
    xread_block=int(TASKIQ_READ_BLOCK_SECONDS * MILLISECONDS_PER_SECOND),
)


broker.on_event(TaskiqEvents.WORKER_STARTUP)(start_worker_presence)
broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)(stop_worker_presence)


@broker.task
async def execute_run_task(run_id: str) -> None:
    await execute_run(UUID(run_id))


class TaskiqRunLauncher:
    async def launch(self, run_id: UUID) -> None:
        await execute_run_task.kiq(str(run_id))
