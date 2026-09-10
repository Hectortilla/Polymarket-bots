"""Soft deletion, retained history, ownership and launch serialization."""

import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from api.bots.errors import (
    BOT_ACTIVE_RUNS_DETAIL,
    BotHasActiveRunsError,
    BotUnavailableError,
)
from api.bots.models import BotRow, BotGraphRevisionRow
from api.bots.store import BotStore
from api.catalog.definitions import CATALOG, NODE_BASED_DEFINITION_ID
from api.catalog.graphs.starter import STARTER_NODE_GRAPH
from api.events.store import EventStore
from api.http.lifecycle import ApiRunLifecycle
from api.http.routes.paths import (
    BOT_PATH,
    BOTS_PATH,
    BOT_RUNS_PATH,
    BOT_GRAPH_REVISION_PATH,
    BOT_GRAPH_REVISIONS_PATH,
    RUN_PATH,
    RUNS_PATH,
    RUN_EVENTS_PATH,
    api_route_path,
)
from api.limits.resources import SavedResourceAllowance
from api.runs.models import RunRow
from api.runs.status import RunStatus, TERMINAL_RUN_STATUSES
from api.runs.store import RunStore
from polybot.framework.clock import system_now_utc

from control_plane.auth_fixtures import TEST_HEADERS
from control_plane.limits_fixtures import (
    account_app,
    account_bot,
    limits_services,
    queue_run,
    resource_services,
)


@pytest.mark.parametrize("run_status", list(RunStatus))
def test_delete_requires_every_run_to_be_terminal(limits_services, run_status):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                row = await session.get(RunRow, run.id)
                row.status = run_status
                await session.commit()
            app = account_app(sessions, redis, user)
            app.state.market_discovery = AsyncMock()
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=TEST_HEADERS,
            ) as client:
                response = await client.delete(api_route_path(BOT_PATH, bot_id=bot.id))
            async with sessions() as session:
                stored = await session.get(BotRow, bot.id)
                if run_status in TERMINAL_RUN_STATUSES:
                    assert response.status_code == status.HTTP_204_NO_CONTENT
                    assert response.content == b""
                    assert stored.deleted_at is not None
                else:
                    assert response.status_code == status.HTTP_409_CONFLICT
                    assert response.json()["detail"] == BOT_ACTIVE_RUNS_DETAIL
                    assert stored.deleted_at is None
                assert (await session.get(RunRow, run.id)).status == run_status

    asyncio.run(scenario())


def test_deleted_bot_is_hidden_but_owned_history_and_graph_survive(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, other_bot = await account_bot(sessions)
            stranger, _ = await account_bot(sessions)
            async with sessions() as session:
                bot = await BotStore(session, user.id).create(
                    definition_id=NODE_BASED_DEFINITION_ID,
                    config=CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
                        {"name": "retained graph", "market_slugs": ["fixture"]}
                    ),
                    graph=STARTER_NODE_GRAPH,
                )
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                await ApiRunLifecycle(session).request_stop(
                    run.id, now=system_now_utc()
                )
                events_before = await EventStore(session).read(run.id)
            path = api_route_path(BOT_PATH, bot_id=bot.id)
            async with AsyncClient(
                transport=ASGITransport(app=account_app(sessions, redis, stranger)),
                base_url="http://test",
                headers=TEST_HEADERS,
            ) as client:
                assert (
                    await client.delete(path)
                ).status_code == status.HTTP_404_NOT_FOUND
            app = account_app(sessions, redis, user)
            app.state.market_discovery = AsyncMock()
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=TEST_HEADERS,
            ) as client:
                assert (
                    await client.delete(path)
                ).status_code == status.HTTP_204_NO_CONTENT
                assert (
                    await client.delete(path)
                ).status_code == status.HTTP_404_NOT_FOUND
                assert (
                    await client.delete(api_route_path(BOT_PATH, bot_id=uuid4()))
                ).status_code == status.HTTP_404_NOT_FOUND
                assert (await client.get(path)).status_code == status.HTTP_404_NOT_FOUND
                assert (
                    await client.patch(
                        path,
                        json={
                            "inputs": {"name": "restore", "market_slugs": ["fixture"]}
                        },
                    )
                ).status_code == status.HTTP_404_NOT_FOUND
                assert (
                    await client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot.id))
                ).status_code == status.HTTP_404_NOT_FOUND
                assert (
                    await client.post(
                        api_route_path(BOT_GRAPH_REVISIONS_PATH, bot_id=bot.id),
                        json={"graph": STARTER_NODE_GRAPH.model_dump(mode="json")},
                    )
                ).status_code == status.HTTP_404_NOT_FOUND
                assert (
                    await client.get(
                        api_route_path(
                            BOT_GRAPH_REVISION_PATH,
                            bot_id=bot.id,
                            revision_id=bot.latest_graph_revision.id,
                        )
                    )
                ).status_code == status.HTTP_404_NOT_FOUND
                assert [
                    item["id"]
                    for item in (await client.get(api_route_path(BOTS_PATH))).json()
                ] == [str(other_bot.id)]
                history = (await client.get(api_route_path(RUNS_PATH))).json()
                assert [item["id"] for item in history] == [str(run.id)]
                assert history[0]["bot_deleted"] is True
                detail = await client.get(api_route_path(RUN_PATH, run_id=run.id))
                assert detail.status_code == status.HTTP_200_OK
                assert detail.json()["graph"] == STARTER_NODE_GRAPH.model_dump(
                    mode="json"
                )
                assert detail.json()["config"] == run.config.model_dump(mode="json")
                assert detail.json()["bot_deleted"] is True
                assert (
                    await client.get(api_route_path(RUN_EVENTS_PATH, run_id=run.id))
                ).status_code == status.HTTP_200_OK
            async with AsyncClient(
                transport=ASGITransport(app=account_app(sessions, redis, stranger)),
                base_url="http://test",
                headers=TEST_HEADERS,
            ) as client:
                assert (
                    await client.get(api_route_path(RUN_PATH, run_id=run.id))
                ).status_code == status.HTTP_404_NOT_FOUND
                assert (
                    await client.get(api_route_path(RUN_EVENTS_PATH, run_id=run.id))
                ).status_code == status.HTTP_404_NOT_FOUND
            async with sessions() as session:
                assert (
                    await session.get(BotRow, bot.id)
                ).config == bot.config.model_dump(mode="json")
                assert (
                    await session.get(BotGraphRevisionRow, bot.latest_graph_revision.id)
                    is not None
                )
                assert await EventStore(session).read(run.id) == events_before
                assert await SavedResourceAllowance(session, user.id).count_bots() == 1
                assert (
                    await BotStore(session, user.id).update_config(bot.id, bot.config)
                    is None
                )
                assert (
                    await BotStore(session, user.id).append_revision(
                        bot.id, STARTER_NODE_GRAPH
                    )
                    is None
                )
                with pytest.raises(BotUnavailableError):
                    await RunStore(session).create_from_bot(bot)

    asyncio.run(scenario())


@pytest.mark.parametrize("delete_first", [True, False])
def test_launch_and_delete_serialize_on_the_bot(limits_services, delete_first):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            async with sessions() as first, sessions() as second:
                await BotStore(first, user.id).read(bot.id, lock=True)
                second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
                if delete_first:
                    pending = asyncio.create_task(RunStore(second).create_from_bot(bot))
                else:
                    pending = asyncio.create_task(
                        BotStore(second, user.id).soft_delete(bot.id)
                    )
                try:
                    async with asyncio.timeout(5):
                        while not await first.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                            {"pid": second_pid},
                        ):
                            await asyncio.sleep(0.01)
                    if delete_first:
                        assert await BotStore(first, user.id).soft_delete(bot.id)
                        with pytest.raises(BotUnavailableError):
                            await pending
                    else:
                        await RunStore(first).create_from_bot(bot)
                        with pytest.raises(BotHasActiveRunsError):
                            await pending
                finally:
                    if not pending.done():
                        pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())
