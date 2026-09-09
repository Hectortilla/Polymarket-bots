"""Persistence operations for the editable graph-template catalog."""

from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.catalog.graphs.contracts import NodeGraph
from api.graph_templates.contracts import (
    GraphTemplateCreate,
    GraphTemplateRead,
    GraphTemplateUpdate,
)
from api.graph_templates.models import GraphTemplateRow
from api.limits.resources import SavedResourceAllowance


class GraphTemplateStore:
    def __init__(self, session: AsyncSession, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id
        self._owned_templates_statement = select(GraphTemplateRow).where(
            GraphTemplateRow.owner_user_id == owner_user_id
        )

    async def create(self, request: GraphTemplateCreate) -> GraphTemplateRead:
        await SavedResourceAllowance(self._session, self._owner_user_id).reserve_template()
        row = GraphTemplateRow(
            owner_user_id=self._owner_user_id,
            name=request.name,
            graph=request.graph.model_dump(mode="json"),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return self.read_from_row(row)

    async def read(self, template_id: UUID) -> GraphTemplateRead | None:
        row = (
            await self._session.execute(
                self._owned_templates_statement.where(GraphTemplateRow.id == template_id)
            )
        ).scalar_one_or_none()
        return None if row is None else self.read_from_row(row)

    async def list(self) -> tuple[GraphTemplateRead, ...]:
        rows = (
            await self._session.execute(
                self._owned_templates_statement.order_by(
                    GraphTemplateRow.name,
                    GraphTemplateRow.id,
                )
            )
        ).scalars()
        return tuple(self.read_from_row(row) for row in rows)

    async def update(
        self,
        template_id: UUID,
        request: GraphTemplateUpdate,
    ) -> GraphTemplateRead | None:
        row = (
            await self._session.execute(
                self._owned_templates_statement.where(GraphTemplateRow.id == template_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if request.name is not None:
            row.name = request.name
        if request.graph is not None:
            row.graph = request.graph.model_dump(mode="json")
        row.updated_at = system_now_utc()
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return self.read_from_row(row)

    @staticmethod
    def read_from_row(row: GraphTemplateRow) -> GraphTemplateRead:
        return GraphTemplateRead(
            id=row.id,
            name=row.name,
            graph=NodeGraph.model_validate(row.graph),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
