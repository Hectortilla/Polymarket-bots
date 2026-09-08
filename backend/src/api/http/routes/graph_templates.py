"""Editable reusable graph-template endpoints."""

from collections.abc import Awaitable
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import CurrentUserDependency
from api.graph_templates.contracts import (
    GraphTemplateCreate,
    GraphTemplateRead,
    GraphTemplateUpdate,
)
from api.graph_templates.store import GraphTemplateStore
from api.http.dependencies import SessionFactoryDependency
from api.http.responses import (
    CONFLICT_RESPONSE,
    NOT_FOUND_AND_CONFLICT_RESPONSES,
    NOT_FOUND_RESPONSE,
)
from api.http.routes.graph_template_lookup import (
    require_graph_template,
)
from api.http.routes.paths import (
    CREATE_GRAPH_TEMPLATE_OPERATION_ID,
    GRAPH_TEMPLATE_PATH,
    GRAPH_TEMPLATES_PATH,
    LIST_GRAPH_TEMPLATES_OPERATION_ID,
    READ_GRAPH_TEMPLATE_OPERATION_ID,
    UPDATE_GRAPH_TEMPLATE_OPERATION_ID,
)

GRAPH_TEMPLATE_NAME_CONFLICT_DETAIL = "graph template name already exists"

router = APIRouter()


@router.post(
    GRAPH_TEMPLATES_PATH,
    response_model=GraphTemplateRead,
    status_code=status.HTTP_201_CREATED,
    operation_id=CREATE_GRAPH_TEMPLATE_OPERATION_ID,
    responses=CONFLICT_RESPONSE,
)
async def create_graph_template(
    request: GraphTemplateCreate,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
) -> GraphTemplateRead:
    async with session_factory() as session:
        return await _persist_template_write(
            session,
            GraphTemplateStore(session, user.id).create(request),
        )


@router.get(
    GRAPH_TEMPLATES_PATH,
    response_model=list[GraphTemplateRead],
    operation_id=LIST_GRAPH_TEMPLATES_OPERATION_ID,
)
async def list_graph_templates(
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
) -> tuple[GraphTemplateRead, ...]:
    async with session_factory() as session:
        return await GraphTemplateStore(session, user.id).list()


@router.get(
    GRAPH_TEMPLATE_PATH,
    response_model=GraphTemplateRead,
    operation_id=READ_GRAPH_TEMPLATE_OPERATION_ID,
    responses=NOT_FOUND_RESPONSE,
)
async def read_graph_template(
    template_id: UUID,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
) -> GraphTemplateRead:
    async with session_factory() as session:
        template = await GraphTemplateStore(session, user.id).read(template_id)
    return require_graph_template(template)


@router.patch(
    GRAPH_TEMPLATE_PATH,
    response_model=GraphTemplateRead,
    operation_id=UPDATE_GRAPH_TEMPLATE_OPERATION_ID,
    responses=NOT_FOUND_AND_CONFLICT_RESPONSES,
)
async def update_graph_template(
    template_id: UUID,
    request: GraphTemplateUpdate,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
) -> GraphTemplateRead:
    async with session_factory() as session:
        template = await _persist_template_write(
            session,
            GraphTemplateStore(session, user.id).update(template_id, request),
        )
    return require_graph_template(template)


async def _persist_template_write(
    session: AsyncSession,
    write: Awaitable[GraphTemplateRead | None],
) -> GraphTemplateRead | None:
    try:
        return await write
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            GRAPH_TEMPLATE_NAME_CONFLICT_DETAIL,
        ) from error
