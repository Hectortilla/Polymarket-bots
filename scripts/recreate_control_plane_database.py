"""Recreate the explicitly configured control-plane PostgreSQL database."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from polybot_control_plane.database import DATABASE_URL_ENV, async_database_url

MAINTENANCE_DATABASE = "postgres"
PROTECTED_DATABASES = frozenset({MAINTENANCE_DATABASE, "template0", "template1"})
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _database_urls(raw_url: str) -> tuple[URL, URL]:
    target_url = async_database_url(raw_url)
    database_name = cast(str, target_url.database)
    if database_name.lower() in PROTECTED_DATABASES:
        raise ValueError(f"refusing to recreate protected database {database_name!r}")
    return target_url, target_url.set(database=MAINTENANCE_DATABASE)


def _quoted_database_name(database_name: str) -> str:
    return postgresql.dialect().identifier_preparer.quote_identifier(database_name)


async def _recreate_database(target_url: URL, maintenance_url: URL) -> None:
    database_name = target_url.database
    if database_name is None:
        raise ValueError("database recreation requires a database name")

    engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name "
                    "AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            quoted_name = _quoted_database_name(database_name)
            await connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_name}"))
            await connection.execute(text(f"CREATE DATABASE {quoted_name}"))
    finally:
        await engine.dispose()


def _upgrade_to_head(target_url: URL) -> None:
    config = Config(PROJECT_ROOT / "alembic.ini")
    rendered_url = target_url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered_url)
    command.upgrade(config, "head")


def main() -> int:
    raw_url = os.getenv(DATABASE_URL_ENV)
    if raw_url is None:
        raise SystemExit(f"{DATABASE_URL_ENV} is not configured")

    try:
        target_url, maintenance_url = _database_urls(raw_url)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    safe_url = target_url.render_as_string(hide_password=True)
    print(f"Recreating {safe_url}")
    asyncio.run(_recreate_database(target_url, maintenance_url))
    _upgrade_to_head(target_url)
    print("Database recreated and migrated to Alembic head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
