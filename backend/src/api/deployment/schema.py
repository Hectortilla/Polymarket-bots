"""Forward migrations and fail-closed application/schema compatibility."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.deployment.settings import StartupSettings
from api.io_policy import DATABASE_CONNECT_ARGS, DEPENDENCY_TIMEOUT_SECONDS

ALEMBIC_CONFIG = Path("backend/alembic.ini")


class DeploymentSchema:
    def __init__(self, settings: StartupSettings) -> None:
        self.settings = settings

    def migrate(self) -> None:
        command.upgrade(self.configuration(), "head")

    def configuration(self) -> Config:
        config = Config(str(ALEMBIC_CONFIG))
        config.set_main_option("sqlalchemy.hide_parameters", "true")
        config.set_main_option(
            "sqlalchemy.url",
            self.settings.database_url.get_secret_value().replace("%", "%%"),
        )
        return config

    async def require_compatible(self) -> None:
        expected = await asyncio.to_thread(self.expected_revision)
        engine = create_async_engine(
            self.settings.database_url.get_secret_value(),
            hide_parameters=True,
            connect_args=DATABASE_CONNECT_ARGS,
            pool_timeout=DEPENDENCY_TIMEOUT_SECONDS,
        )
        try:
            async with engine.connect() as connection:
                actual = (
                    (
                        await connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        )
                    )
                    .scalars()
                    .all()
                )
            if actual != [expected]:
                raise RuntimeError("database schema is incompatible with this release")
        finally:
            await engine.dispose()

    def expected_revision(self) -> str | None:
        return ScriptDirectory.from_config(self.configuration()).get_current_head()
