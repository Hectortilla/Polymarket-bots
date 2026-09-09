from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context

# Importing rows registers every control-plane table in shared SQLModel metadata.
from api.auth.models import SessionRow, UserRow  # noqa: F401
from api.auth.recovery.models import AccountTokenRow  # noqa: F401
from api.bots.models import BotGraphRevisionRow, BotRow  # noqa: F401
from api.graph_templates.models import GraphTemplateRow  # noqa: F401
from api.runs.models import RunRow  # noqa: F401
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_migrations_online())
