"""Exercise release compatibility against isolated PostgreSQL revision tables."""

import asyncio
import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from api.database import async_database_url
from api.deployment import schema as schema_module
from api.deployment.schema import DeploymentSchema
from api.deployment.settings import StartupSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from control_plane.service_config import (
    POSTGRES_NOT_CONFIGURED_SKIP_REASON,
    TEST_POSTGRES_URL_ENV,
)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "revision", [None, "stale_revision", "unknown_revision", "matching"]
)
def test_release_requires_exact_database_revision(revision: str | None) -> None:
    raw_url = os.getenv(TEST_POSTGRES_URL_ENV)
    if raw_url is None:
        pytest.skip(POSTGRES_NOT_CONFIGURED_SKIP_REASON)
    url = async_database_url(raw_url).render_as_string(hide_password=False)
    schema = DeploymentSchema(
        StartupSettings(database_url=url, redis_url="redis://localhost")
    )
    actual = schema.expected_revision() if revision == "matching" else revision
    namespace = "review_schema_" + uuid4().hex

    async def scenario():
        setup_engine = create_async_engine(url)
        try:
            async with setup_engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
                await connection.execute(
                    text(
                        f'CREATE TABLE "{namespace}".alembic_version (version_num TEXT)'
                    )
                )
                if actual is not None:
                    await connection.execute(
                        text(
                            f'INSERT INTO "{namespace}".alembic_version VALUES (:revision)'
                        ),
                        {"revision": actual},
                    )

            def isolated_engine(database_url, **options):
                options["connect_args"] = {
                    **options["connect_args"],
                    "server_settings": {"search_path": namespace},
                }
                return create_async_engine(database_url, **options)

            with patch.object(schema_module, "create_async_engine", isolated_engine):
                if revision == "matching":
                    await schema.require_compatible()
                else:
                    with pytest.raises(
                        RuntimeError, match="database schema is incompatible"
                    ):
                        await schema.require_compatible()
        finally:
            async with setup_engine.begin() as connection:
                await connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{namespace}" CASCADE')
                )
            await setup_engine.dispose()

    asyncio.run(scenario())
