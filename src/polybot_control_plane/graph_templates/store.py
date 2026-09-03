"""Persistence operations for the editable graph-template catalog."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from polybot.framework.clock import system_now_utc
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.graph_templates.contracts import (
    GraphTemplateCreate,
    GraphTemplateRead,
    GraphTemplateUpdate,
)
from polybot_control_plane.graph_templates.models import GraphTemplateRow


class GraphTemplateStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, request: GraphTemplateCreate) -> GraphTemplateRead:
        row = GraphTemplateRow(
            name=request.name,
            graph=request.graph.model_dump(mode="json"),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return self.read_from_row(row)

    async def read(self, template_id: UUID) -> GraphTemplateRead | None:
        row = await self._session.get(GraphTemplateRow, template_id)
        return None if row is None else self.read_from_row(row)

    async def list(self) -> tuple[GraphTemplateRead, ...]:
        rows = (
            await self._session.execute(
                select(GraphTemplateRow).order_by(
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
        row = await self._session.get(GraphTemplateRow, template_id)
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
