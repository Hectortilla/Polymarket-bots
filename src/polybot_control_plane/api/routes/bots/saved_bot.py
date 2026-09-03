"""Saved-bot CRUD and graph-revision endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from polybot_control_plane.api.dependencies import SessionFactoryDependency
from polybot_control_plane.api.routes.bots.validation import (
    GRAPH_REVISION_FORBIDDEN_DETAIL,
    GRAPH_REVISION_REQUIRED_DETAIL,
    parse_config,
    require_bot,
    require_catalog_entry,
    require_graph_contract,
    resolve_bot_graph,
)
from polybot_control_plane.api.responses import NOT_FOUND_RESPONSE
from polybot_control_plane.api.routes.paths import (
    BOTS_PATH,
    BOT_GRAPH_REVISION_PATH,
    BOT_GRAPH_REVISIONS_PATH,
    BOT_PATH,
    CREATE_BOT_GRAPH_REVISION_OPERATION_ID,
    CREATE_BOT_OPERATION_ID,
    LIST_BOTS_OPERATION_ID,
    READ_BOT_GRAPH_REVISION_OPERATION_ID,
    READ_BOT_OPERATION_ID,
    UPDATE_BOT_OPERATION_ID,
)
from polybot_control_plane.bots.contracts import (
    BotCreate,
    BotGraphRevisionCreate,
    BotGraphRevisionRead,
    BotRead,
    BotUpdate,
)
from polybot_control_plane.bots.store import BotStore


BOT_GRAPH_REVISION_NOT_FOUND_DETAIL = "bot graph revision not found"

router = APIRouter()


@router.post(
    BOTS_PATH,
    response_model=BotRead,
    status_code=status.HTTP_201_CREATED,
    operation_id=CREATE_BOT_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def create_bot(
    request: BotCreate,
    session_factory: SessionFactoryDependency,
) -> BotRead:
    definition = require_catalog_entry(request.definition_id)
    config = parse_config(definition, request.inputs, request.model_dump())
    async with session_factory() as session:
        graph = await resolve_bot_graph(
            session,
            definition,
            request.graph_template_id,
        )
        return await BotStore(session).create(
            definition_id=request.definition_id,
            config=config,
            graph=graph,
        )


@router.get(
    BOTS_PATH,
    response_model=list[BotRead],
    operation_id=LIST_BOTS_OPERATION_ID,
)
async def list_bots(
    session_factory: SessionFactoryDependency,
) -> tuple[BotRead, ...]:
    async with session_factory() as session:
        return await BotStore(session).list()


@router.get(
    BOT_PATH,
    response_model=BotRead,
    operation_id=READ_BOT_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def read_bot(
    bot_id: UUID,
    session_factory: SessionFactoryDependency,
) -> BotRead:
    async with session_factory() as session:
        bot = await BotStore(session).read(bot_id)
    return require_bot(bot)


@router.patch(
    BOT_PATH,
    response_model=BotRead,
    operation_id=UPDATE_BOT_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def update_bot(
    bot_id: UUID,
    request: BotUpdate,
    session_factory: SessionFactoryDependency,
) -> BotRead:
    async with session_factory() as session:
        store = BotStore(session)
        bot = require_bot(await store.read(bot_id, lock=True))
        definition = require_catalog_entry(bot.definition_id)
        config = parse_config(definition, request.inputs, request.model_dump())
        updated = await store.update_config(bot_id, config)
    return require_bot(updated)


@router.post(
    BOT_GRAPH_REVISIONS_PATH,
    response_model=BotRead,
    status_code=status.HTTP_201_CREATED,
    operation_id=CREATE_BOT_GRAPH_REVISION_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def create_bot_graph_revision(
    bot_id: UUID,
    request: BotGraphRevisionCreate,
    session_factory: SessionFactoryDependency,
) -> BotRead:
    async with session_factory() as session:
        store = BotStore(session)
        bot = require_bot(await store.read(bot_id))
        definition = require_catalog_entry(bot.definition_id)
        require_graph_contract(
            definition,
            request.graph,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            required_detail=GRAPH_REVISION_REQUIRED_DETAIL,
            forbidden_detail=GRAPH_REVISION_FORBIDDEN_DETAIL,
        )
        updated = await store.append_revision(bot_id, request.graph)
    return require_bot(updated)


@router.get(
    BOT_GRAPH_REVISION_PATH,
    response_model=BotGraphRevisionRead,
    operation_id=READ_BOT_GRAPH_REVISION_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def read_bot_graph_revision(
    bot_id: UUID,
    revision_id: UUID,
    session_factory: SessionFactoryDependency,
) -> BotGraphRevisionRead:
    async with session_factory() as session:
        revision = await BotStore(session).read_revision(bot_id, revision_id)
    if revision is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            BOT_GRAPH_REVISION_NOT_FOUND_DETAIL,
        )
    return revision
