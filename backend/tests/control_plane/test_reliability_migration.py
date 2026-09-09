"""The reliability migration preserves populated account and run history."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from api.auth.models import UserRow
from api.events.store import EventStore
from api.runs.models import RunRow
from api.runs.store import RunStore
from polybot.framework.clock import system_now_utc

from control_plane.limits_fixtures import account_bot, queue_run, resource_services
from control_plane.limits_fixtures import limits_services as limits_services


def test_upgrade_preserves_existing_accounts_and_terminal_history(limits_services):
    async def seed():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                await RunStore(session).request_stop(run.id, now=system_now_utc())
                events = await EventStore(session).read(run.id)
                return user.id, run.id, events

    user_id, run_id, events = asyncio.run(seed())
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", limits_services[0])
    # Downgrading only the new nullable metadata recreates a populated 0005 DB.
    command.downgrade(config, "0005")
    command.upgrade(config, "head")

    async def verify():
        async with resource_services(limits_services) as (sessions, redis):
            async with sessions() as session:
                assert await session.get(UserRow, user_id) is not None
                row = await session.get(RunRow, run_id)
                assert (
                    row.launch_key
                    is row.execution_token
                    is row.delivery_attempted_at
                    is None
                )
                assert await EventStore(session).read(run_id) == events

    asyncio.run(verify())
