"""Seed an admin exclusively in disposable browser and HTTPS acceptance servers."""

from contextlib import asynccontextmanager
from uuid import uuid4

from api.auth.models import UserRow
from api.auth.passwords import hash_password
from polybot.framework.clock import system_now_utc
from sqlalchemy.dialects.postgresql import insert

ADMIN_EMAIL = "browser-admin@example.com"
ADMIN_PASSWORD = "disposable admin browser password 123"


def install_admin_fixture(app):
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            async with application.state.session_factory() as session:
                await session.execute(
                    insert(UserRow)
                    .values(
                        id=uuid4(),
                        email=ADMIN_EMAIL,
                        password_hash=await hash_password(ADMIN_PASSWORD),
                        created_at=system_now_utc(),
                        email_verified_at=system_now_utc(),
                        is_admin=True,
                    )
                    .on_conflict_do_nothing()
                )
                await session.commit()
            yield

    app.router.lifespan_context = lifespan
