"""Private command dispatch with bounded database and Redis resource ownership."""

from redis.asyncio import Redis

from api.deployment.settings import StartupSettings
from api.execution.worker.database import create_worker_database
from api.io_policy import REDIS_SOCKET_OPTIONS
from api.operations.commands import CommandRequest, ReadCommand
from api.operations.contracts import (
    OperationResult,
    OperationStatus,
    RunInspection,
    RunInspectionList,
)
from api.operations.control import OperatorControl
from api.operations.inspection import RunInspector
from api.operations.monitor import OperationMonitor


async def execute(
    request: CommandRequest, settings: StartupSettings, actor: str
) -> OperationResult | OperationStatus | RunInspection | RunInspectionList:
    engine, sessions = create_worker_database(settings.database_url.get_secret_value())
    try:
        if request.command is ReadCommand.LIST_RUNS:
            async with sessions() as session:
                return RunInspectionList(
                    runs=await RunInspector(session).list_unfinished()
                )
        if request.command is ReadCommand.INSPECT_RUN:
            async with sessions() as session:
                return await RunInspector(session).read(request.target)
        if request.command is ReadCommand.STATUS:
            redis = Redis.from_url(
                settings.redis_url.get_secret_value(), **REDIS_SOCKET_OPTIONS
            )
            try:
                alerts = await OperationMonitor(
                    sessions,
                    redis,
                    lease_seconds=settings.lease_seconds,
                    storage_path=settings.storage_probe_path,
                ).tick()
                return OperationStatus(alerts=alerts)
            finally:
                await redis.aclose()
        async with sessions() as session:
            outcome = await OperatorControl(session, actor).apply(
                request.command, request.target
            )
            return OperationResult(
                action=request.command, target=request.target, outcome=outcome
            )
    finally:
        await engine.dispose()
