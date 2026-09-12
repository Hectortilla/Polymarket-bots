"""Atomic saved-bot configuration endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from api.auth.dependencies import CurrentUserDependency
from api.bots.contracts import (
    BotCreate,
    BotRead,
    BotUpdate,
)
from api.bots.errors import BOT_ACTIVE_RUNS_DETAIL, BotHasActiveRunsError
from api.bots.store import BotStore
from api.http.dependencies import (
    MarketDiscoveryDependency,
    SessionFactoryDependency,
)
from api.http.responses import (
    NOT_FOUND_AND_CONFLICT_RESPONSES,
    NOT_FOUND_RESPONSE,
    SERVICE_UNAVAILABLE_RESPONSE,
)
from api.http.routes.bots.market_validation import (
    validate_new_market_selections,
)
from api.http.routes.bots.validation import (
    BOT_NOT_FOUND_DETAIL,
    parse_config,
    require_bot,
    require_catalog_entry,
)
from api.http.routes.paths import (
    BOT_PATH,
    BOTS_PATH,
    CREATE_BOT_OPERATION_ID,
    DELETE_BOT_OPERATION_ID,
    LIST_BOTS_OPERATION_ID,
    READ_BOT_OPERATION_ID,
    UPDATE_BOT_OPERATION_ID,
)

router = APIRouter()


@router.post(
    BOTS_PATH,
    response_model=BotRead,
    status_code=status.HTTP_201_CREATED,
    operation_id=CREATE_BOT_OPERATION_ID,
    responses={**NOT_FOUND_RESPONSE, **SERVICE_UNAVAILABLE_RESPONSE},
)
async def create_bot(
    request: BotCreate,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
    discovery: MarketDiscoveryDependency,
) -> BotRead:
    definition = require_catalog_entry(request.definition_id)
    config = parse_config(
        definition, request.inputs, request.graph, request.model_dump()
    )
    async with session_factory() as session:
        await validate_new_market_selections(config, discovery)
        return await BotStore(session, user.id).create(
            definition_id=request.definition_id,
            config=config,
        )


@router.get(
    BOTS_PATH,
    response_model=list[BotRead],
    operation_id=LIST_BOTS_OPERATION_ID,
)
async def list_bots(
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
) -> tuple[BotRead, ...]:
    async with session_factory() as session:
        return await BotStore(session, user.id).list()


@router.get(
    BOT_PATH,
    response_model=BotRead,
    operation_id=READ_BOT_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def read_bot(
    bot_id: UUID,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
) -> BotRead:
    async with session_factory() as session:
        bot = await BotStore(session, user.id).read(bot_id)
    return require_bot(bot)


@router.delete(
    BOT_PATH,
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id=DELETE_BOT_OPERATION_ID,
    responses=NOT_FOUND_AND_CONFLICT_RESPONSES,
)
async def delete_bot(
    bot_id: UUID,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
) -> Response:
    async with session_factory() as session:
        try:
            deleted = await BotStore(session, user.id).soft_delete(bot_id)
        except BotHasActiveRunsError:
            raise HTTPException(
                status.HTTP_409_CONFLICT, BOT_ACTIVE_RUNS_DETAIL
            ) from None
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOT_NOT_FOUND_DETAIL)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    BOT_PATH,
    response_model=BotRead,
    operation_id=UPDATE_BOT_OPERATION_ID,
    responses={**NOT_FOUND_RESPONSE, **SERVICE_UNAVAILABLE_RESPONSE},
)
async def update_bot(
    bot_id: UUID,
    request: BotUpdate,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
    discovery: MarketDiscoveryDependency,
) -> BotRead:
    async with session_factory() as session:
        store = BotStore(session, user.id)
        bot = require_bot(await store.read(bot_id, lock=True))
        definition = require_catalog_entry(bot.definition_id)
        config = parse_config(
            definition, request.inputs, request.graph, request.model_dump()
        )
        await validate_new_market_selections(
            config, discovery, previous_config=bot.config
        )
        updated = await store.update_config(bot_id, config)
    return require_bot(updated)
