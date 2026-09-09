"""Database engine and session construction for worker processes."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.io_policy import DATABASE_CONNECT_ARGS, DEPENDENCY_TIMEOUT_SECONDS


def create_worker_database(
    database_url: str,
) -> tuple[
    AsyncEngine,
    async_sessionmaker[AsyncSession],
]:
    engine = create_async_engine(
        database_url,
        hide_parameters=True,
        connect_args=DATABASE_CONNECT_ARGS,
        pool_timeout=DEPENDENCY_TIMEOUT_SECONDS,
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)
