"""Focused tests for saved-bot persistence behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from api.bots.models import BotRow
from api.bots.store import BotStore
from api.catalog.definitions import CATALOG, WINNER_DEFINITION_ID
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.auth_fixtures import TEST_USER_ID


def test_list_materializes_complete_bots_without_additional_queries() -> None:
    first_config = CATALOG[WINNER_DEFINITION_ID].parse_config(
        {"name": "first", "max_order_size": "1"}
    )
    second_config = CATALOG[WINNER_DEFINITION_ID].parse_config(
        {"name": "second", "max_order_size": "2"}
    )
    rows = (
        BotRow(
            owner_user_id=TEST_USER_ID,
            definition_id=WINNER_DEFINITION_ID,
            config=first_config.model_dump(mode="json"),
        ),
        BotRow(
            owner_user_id=TEST_USER_ID,
            definition_id=WINNER_DEFINITION_ID,
            config=second_config.model_dump(mode="json"),
        ),
    )
    result = MagicMock()
    result.scalars.return_value = rows
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    store = BotStore(session, TEST_USER_ID)

    bots = asyncio.run(store.list())

    assert tuple(bot.id for bot in bots) == tuple(row.id for row in rows)
    assert tuple(bot.config.name for bot in bots) == ("first", "second")
    assert all(bot.config.graph is None for bot in bots)
    session.execute.assert_awaited_once()
