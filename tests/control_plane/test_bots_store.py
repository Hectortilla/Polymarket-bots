"""Focused tests for saved-bot persistence behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

from sqlalchemy.ext.asyncio import AsyncSession

from polybot_control_plane.bots.models import BotRow
from polybot_control_plane.bots.store import BotStore
from polybot_control_plane.catalog.definitions import CATALOG, WINNER_DEFINITION_ID


def test_list_materializes_bots_after_loading_latest_revisions() -> None:
    first_config = CATALOG[WINNER_DEFINITION_ID].parse_config(
        {"name": "first", "max_order_size": "1"}
    )
    second_config = CATALOG[WINNER_DEFINITION_ID].parse_config(
        {"name": "second", "max_order_size": "2"}
    )
    rows = (
        BotRow(
            definition_id=WINNER_DEFINITION_ID,
            config=first_config.model_dump(mode="json"),
        ),
        BotRow(
            definition_id=WINNER_DEFINITION_ID,
            config=second_config.model_dump(mode="json"),
        ),
    )
    result = MagicMock()
    result.scalars.return_value = rows
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    store = BotStore(session)
    store.latest_revision = AsyncMock(return_value=None)

    bots = asyncio.run(store.list())

    assert tuple(bot.id for bot in bots) == tuple(row.id for row in rows)
    assert tuple(bot.config.name for bot in bots) == ("first", "second")
    assert all(bot.latest_graph_revision is None for bot in bots)
    store.latest_revision.assert_has_awaits([call(row.id) for row in rows])
