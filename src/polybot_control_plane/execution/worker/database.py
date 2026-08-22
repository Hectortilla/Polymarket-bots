"""Database engine and session construction for worker processes."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from polybot_control_plane.database import configured_database_url


def create_worker_database() -> tuple[
    AsyncEngine,
    async_sessionmaker[AsyncSession],
]:
    engine = create_async_engine(configured_database_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)
