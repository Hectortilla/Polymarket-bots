from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config import AppConfig


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_SCRIPT_LOCATION = BACKEND_ROOT / "alembic"
POSTGRES_ADMIN_URL_ENV = "POLYFOLLOW_POSTGRES_ADMIN_URL"
DEFAULT_ADMIN_DATABASE = "postgres"
DEFAULT_ADMIN_USERNAME = "postgres"
POSTGRES_DIALECT_PREFIX = "postgresql"


def configured_database_url(explicit_database_url: str | None = None) -> str:
    if explicit_database_url:
        return explicit_database_url
    return AppConfig.from_env().database.postgres_url


def configured_admin_database_url(
    explicit_admin_database_url: str | None = None,
) -> str | None:
    if explicit_admin_database_url:
        return explicit_admin_database_url
    return os.getenv(POSTGRES_ADMIN_URL_ENV)


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def postgres_admin_url(
    database_url: str,
    *,
    admin_database: str = DEFAULT_ADMIN_DATABASE,
    admin_database_url: str | None = None,
) -> URL:
    configured_admin_url = configured_admin_database_url(admin_database_url)
    if configured_admin_url:
        url = make_url(configured_admin_url)
        if not url.drivername.startswith(POSTGRES_DIALECT_PREFIX):
            raise ValueError(
                "Admin database URL must be a PostgreSQL URL."
            )
        return url

    url = make_url(database_url)
    if not url.drivername.startswith(POSTGRES_DIALECT_PREFIX):
        raise ValueError(
            "Database create/drop utilities require a PostgreSQL URL."
        )
    if not url.database:
        raise ValueError("PostgreSQL URL must include a database name.")
    return URL.create(
        drivername=url.drivername,
        username=DEFAULT_ADMIN_USERNAME,
        password=None,
        host=url.host,
        port=url.port,
        database=admin_database,
        query=url.query,
    )


def target_database_name(database_url: str) -> str:
    database_name = make_url(database_url).database
    if not database_name:
        raise ValueError("Database URL must include a database name.")
    return database_name


def target_role_name(database_url: str) -> str:
    role_name = make_url(database_url).username
    if not role_name:
        raise ValueError("Database URL must include a username.")
    return role_name


def target_role_password(database_url: str) -> str | None:
    return make_url(database_url).password


def ensure_target_is_not_admin_database(
    database_name: str,
    *,
    admin_database: str,
) -> None:
    if database_name != admin_database:
        return
    raise ValueError("Refusing to operate on the PostgreSQL maintenance database.")


async def quoted_identifier(
    connection: AsyncConnection,
    identifier: str,
) -> str:
    return await connection.run_sync(
        lambda sync_connection: (
            sync_connection.dialect.identifier_preparer.quote(identifier)
        )
    )


async def quoted_literal(connection: AsyncConnection, value: str) -> str:
    literal = await connection.scalar(
        text("SELECT quote_literal(:value)"),
        {"value": value},
    )
    if not isinstance(literal, str):
        raise ValueError("PostgreSQL did not return a quoted literal.")
    return literal


async def database_exists(
    connection: AsyncConnection,
    database_name: str,
) -> bool:
    exists = await connection.scalar(
        text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
        {"database_name": database_name},
    )
    return exists is not None


async def role_exists(
    connection: AsyncConnection,
    role_name: str,
) -> bool:
    exists = await connection.scalar(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role_name"),
        {"role_name": role_name},
    )
    return exists is not None


async def ensure_role(
    connection: AsyncConnection,
    *,
    role_name: str,
    role_password: str | None,
) -> None:
    if await role_exists(connection, role_name):
        print(f"Role already exists: {role_name}")
        return

    quoted_role = await quoted_identifier(connection, role_name)
    if role_password is None:
        await connection.execute(text(f"CREATE ROLE {quoted_role} WITH LOGIN"))
    else:
        quoted_password = await quoted_literal(connection, role_password)
        await connection.execute(
            text(f"CREATE ROLE {quoted_role} WITH LOGIN PASSWORD {quoted_password}")
        )
    print(f"Created role: {role_name}")


async def ensure_database_permissions(
    connection: AsyncConnection,
    *,
    database_name: str,
    role_name: str,
) -> None:
    quoted_database = await quoted_identifier(connection, database_name)
    quoted_role = await quoted_identifier(connection, role_name)
    await connection.execute(
        text(f"ALTER DATABASE {quoted_database} OWNER TO {quoted_role}")
    )
    await connection.execute(
        text(f"GRANT ALL PRIVILEGES ON DATABASE {quoted_database} TO {quoted_role}")
    )


async def grant_public_schema_permissions(
    database_url: str,
    *,
    admin_url: URL,
    role_name: str,
) -> None:
    database_name = target_database_name(database_url)
    engine = create_async_engine(
        admin_url.set(database=database_name),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as connection:
            quoted_role = await quoted_identifier(connection, role_name)
            await connection.execute(
                text(f"GRANT ALL PRIVILEGES ON SCHEMA public TO {quoted_role}")
            )
            await connection.execute(
                text(
                    "GRANT ALL PRIVILEGES ON ALL TABLES "
                    f"IN SCHEMA public TO {quoted_role}"
                )
            )
            await connection.execute(
                text(
                    "GRANT ALL PRIVILEGES ON ALL SEQUENCES "
                    f"IN SCHEMA public TO {quoted_role}"
                )
            )
            await connection.execute(
                text(
                    "GRANT ALL PRIVILEGES ON ALL FUNCTIONS "
                    f"IN SCHEMA public TO {quoted_role}"
                )
            )
    finally:
        await engine.dispose()


async def create_database(
    database_url: str,
    *,
    admin_database: str = DEFAULT_ADMIN_DATABASE,
    admin_database_url: str | None = None,
) -> None:
    database_name = target_database_name(database_url)
    role_name = target_role_name(database_url)
    ensure_target_is_not_admin_database(
        database_name,
        admin_database=admin_database,
    )
    admin_url = postgres_admin_url(
        database_url,
        admin_database=admin_database,
        admin_database_url=admin_database_url,
    )
    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as connection:
            await ensure_role(
                connection,
                role_name=role_name,
                role_password=target_role_password(database_url),
            )

            if await database_exists(connection, database_name):
                print(f"Database already exists: {database_name}")
            else:
                quoted_name = await quoted_identifier(connection, database_name)
                quoted_role = await quoted_identifier(connection, role_name)
                await connection.execute(
                    text(f"CREATE DATABASE {quoted_name} OWNER {quoted_role}")
                )
                print(f"Created database: {database_name}")

            await ensure_database_permissions(
                connection,
                database_name=database_name,
                role_name=role_name,
            )
    finally:
        await engine.dispose()
    await grant_public_schema_permissions(
        database_url,
        admin_url=admin_url,
        role_name=role_name,
    )
    print(f"Granted database privileges to role: {role_name}")


async def drop_database(
    database_url: str,
    *,
    admin_database: str = DEFAULT_ADMIN_DATABASE,
    admin_database_url: str | None = None,
) -> None:
    database_name = target_database_name(database_url)
    ensure_target_is_not_admin_database(
        database_name,
        admin_database=admin_database,
    )
    engine = create_async_engine(
        postgres_admin_url(
            database_url,
            admin_database=admin_database,
            admin_database_url=admin_database_url,
        ),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as connection:
            if not await database_exists(connection, database_name):
                print(f"Database does not exist: {database_name}")
                return

            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name "
                    "AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            quoted_name = await quoted_identifier(connection, database_name)
            await connection.execute(text(f"DROP DATABASE {quoted_name}"))
            print(f"Dropped database: {database_name}")
    finally:
        await engine.dispose()


def upgrade_database(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade_database(database_url: str, revision: str) -> None:
    command.downgrade(alembic_config(database_url), revision)


def show_current_revision(database_url: str) -> None:
    command.current(alembic_config(database_url), verbose=True)


def confirm_destructive_action(args: argparse.Namespace) -> None:
    if args.yes:
        return
    raise SystemExit(
        "Refusing destructive database action without --yes. "
        "Re-run with --yes when you are sure."
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Polyfollow database utility commands.",
    )
    parser.add_argument(
        "--database-url",
        help=(
            "Override POLYFOLLOW_POSTGRES_URL for this command. Defaults to "
            "the configured application database URL."
        ),
    )
    parser.add_argument(
        "--admin-database",
        default=DEFAULT_ADMIN_DATABASE,
        help="PostgreSQL maintenance database used for create/drop commands.",
    )
    parser.add_argument(
        "--admin-database-url",
        help=(
            f"PostgreSQL admin connection URL. Defaults to "
            f"{POSTGRES_ADMIN_URL_ENV}, then a postgres-role URL derived from "
            "the configured database URL."
        ),
    )

    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("create", help="Create the configured database.")
    subcommands.add_parser(
        "migrate",
        help="Apply Alembic migrations to the configured database.",
    )
    subcommands.add_parser(
        "current",
        help="Show the current Alembic revision for the configured database.",
    )

    downgrade_parser = subcommands.add_parser(
        "downgrade",
        help="Downgrade the configured database to an Alembic revision.",
    )
    downgrade_parser.add_argument(
        "revision",
        help='Alembic revision target, for example "base" or "-1".',
    )

    drop_parser = subcommands.add_parser(
        "drop",
        help="Drop the configured database.",
    )
    drop_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm this destructive action.",
    )

    rebuild_parser = subcommands.add_parser(
        "rebuild",
        aliases=["reset"],
        help="Drop, recreate, and migrate the configured database.",
    )
    rebuild_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm this destructive action.",
    )

    return parser.parse_args(argv)


def run_command(args: argparse.Namespace) -> None:
    database_url = configured_database_url(args.database_url)

    match args.command:
        case "create":
            asyncio.run(
                create_database(
                    database_url,
                    admin_database=args.admin_database,
                    admin_database_url=args.admin_database_url,
                )
            )
        case "drop":
            confirm_destructive_action(args)
            asyncio.run(
                drop_database(
                    database_url,
                    admin_database=args.admin_database,
                    admin_database_url=args.admin_database_url,
                )
            )
        case "rebuild" | "reset":
            confirm_destructive_action(args)
            asyncio.run(
                drop_database(
                    database_url,
                    admin_database=args.admin_database,
                    admin_database_url=args.admin_database_url,
                )
            )
            asyncio.run(
                create_database(
                    database_url,
                    admin_database=args.admin_database,
                    admin_database_url=args.admin_database_url,
                )
            )
            upgrade_database(database_url)
        case "migrate":
            upgrade_database(database_url)
        case "downgrade":
            downgrade_database(database_url, args.revision)
        case "current":
            show_current_revision(database_url)
        case _:
            raise SystemExit(f"Unknown database command: {args.command}")


def main(argv: Sequence[str] | None = None) -> None:
    run_command(parse_args(argv))


if __name__ == "__main__":
    main()
