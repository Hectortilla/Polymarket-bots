"""Complete configurations are isolated across bots, queued runs, and edits."""

import asyncio
from uuid import uuid4

from api.bots.models import BotRow
from api.bots.store import BotStore
from api.catalog.definitions import CATALOG, NODE_BASED_DEFINITION_ID
from api.catalog.graphs.contracts import NodeGraph
from api.runs.models import RunRow
from api.runs.store import RunStore
from polybot.framework.clock import system_now_utc
from sqlmodel import SQLModel

from control_plane.graph_fixtures import threshold_buy_graph
from control_plane.limits_fixtures import account_bot, resource_services
from control_plane.limits_fixtures import limits_services as limits_services


def test_complete_snapshots_survive_edits_queueing_and_duplicate_launch(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, _):
            owner, _ = await account_bot(sessions)
            graph = NodeGraph.model_validate(threshold_buy_graph())
            config = (
                CATALOG[NODE_BASED_DEFINITION_ID]
                .parse_config(
                    {
                        "name": "original",
                        "market_slugs": ["fixture"],
                        "max_order_size": "2.500",
                    }
                )
                .model_copy(update={"graph": graph}, deep=True)
            )
            original_document = config.model_dump(mode="json")
            async with sessions() as session:
                bots = BotStore(session, owner.id)
                bot = await bots.create(
                    definition_id=NODE_BASED_DEFINITION_ID, config=config
                )
                launch_key = uuid4()
                first = await RunStore(session).create_from_bot(
                    bot, launch_key=launch_key
                )
                # Build an independent edited graph; typed graph nodes are frozen.
                edited = bot.config.model_copy(update={"name": "edited"}, deep=True)
                edited_graph = graph.model_dump(mode="json")
                edited_graph["nodes"][1]["position"]["x"] += 42
                edited.graph = NodeGraph.model_validate(edited_graph)
                await bots.update_config(bot.id, edited)
                # Stale caller data cannot replace the current saved document.
                second = await RunStore(session).create_from_bot(bot)
                assert second.config == edited
                duplicate = await RunStore(session).create_from_bot(
                    bot, launch_key=launch_key
                )
                assert duplicate.id == first.id
                assert duplicate.config.model_dump(mode="json") == original_document
                session.expire_all()
                persisted = await session.get(RunRow, first.id)
                assert persisted.config_snapshot == original_document
                assert (await session.get(BotRow, bot.id)).config == edited.model_dump(
                    mode="json"
                )
                claimed = await RunStore(session).claim(first.id, now=system_now_utc())
                assert claimed.config.model_dump(mode="json") == original_document
                assert claimed.config.graph != second.config.graph

    asyncio.run(scenario())


def test_copying_configuration_creates_an_independent_bot(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, _):
            owner, _ = await account_bot(sessions)
            graph = NodeGraph.model_validate(threshold_buy_graph())
            config = (
                CATALOG[NODE_BASED_DEFINITION_ID]
                .parse_config({"name": "source", "market_slugs": ["fixture"]})
                .model_copy(update={"graph": graph}, deep=True)
            )
            async with sessions() as session:
                bots = BotStore(session, owner.id)
                original = await bots.create(
                    definition_id=NODE_BASED_DEFINITION_ID, config=config
                )
                copied = await bots.create(
                    definition_id=original.definition_id, config=original.config
                )
                changed = original.config.model_copy(
                    update={"name": "changed"}, deep=True
                )
                changed_graph = graph.model_dump(mode="json")
                changed_graph["nodes"][1]["position"]["x"] += 1
                changed.graph = NodeGraph.model_validate(changed_graph)
                await bots.update_config(original.id, changed)
                session.expire_all()
                assert (await bots.read(copied.id)).config == copied.config
                assert (await bots.read(original.id)).config != copied.config
                assert original.id != copied.id

    asyncio.run(scenario())


def test_schema_has_no_template_or_revision_resources():
    assert "graph_templates" not in SQLModel.metadata.tables
    assert "bot_graph_revisions" not in SQLModel.metadata.tables
    assert "config_snapshot" in RunRow.__table__.columns
    assert "bot_graph_revision_id" not in RunRow.__table__.columns
