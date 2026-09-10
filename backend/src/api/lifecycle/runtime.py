"""Schema-gated lifecycle command execution and resource ownership."""

from uuid import UUID

from api.deployment.schema import DeploymentSchema
from api.deployment.settings import StartupSettings
from api.execution.worker.database import create_worker_database
from api.lifecycle.commands import DataCommand
from api.lifecycle.maintenance import DataMaintenance
from api.lifecycle.restoration import RestoreQuarantine


async def execute(
    command: DataCommand, user_id: UUID | None, settings: StartupSettings, actor: str
) -> None:
    await DeploymentSchema(settings).require_compatible()
    engine, sessions = create_worker_database(settings.database_url.get_secret_value())
    try:
        if command is DataCommand.CLEAN:
            await DataMaintenance(sessions).tick()
        else:
            async with sessions() as session:
                restore = RestoreQuarantine(session, actor)
                if command is DataCommand.QUARANTINE_RESTORE:
                    await restore.apply()
                else:
                    await restore.approve_account(user_id)
    finally:
        await engine.dispose()
