"""Database engine and session construction for worker processes."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

def create_worker_database(database_url: str) -> tuple[
    AsyncEngine,
    async_sessionmaker[AsyncSession],
]:
    engine = create_async_engine(database_url, hide_parameters=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
