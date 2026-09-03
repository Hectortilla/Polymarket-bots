"""Persistence boundary for saved bots and immutable graph revisions."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from polybot.framework.clock import system_now_utc
from polybot_control_plane.bots.contracts import BotGraphRevisionRead, BotRead
from polybot_control_plane.bots.models import BotGraphRevisionRow, BotRow
from polybot_control_plane.bots.revisions import (
    FIRST_GRAPH_REVISION_NUMBER,
    next_graph_revision_number,
)
from polybot_control_plane.catalog.values import DefinitionId
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.runs.contracts import PaperRunConfig


class BotStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        definition_id: DefinitionId,
        config: PaperRunConfig,
        graph: NodeGraph | None,
    ) -> BotRead:
        row = BotRow(
            definition_id=definition_id,
            config=config.model_dump(mode="json"),
        )
        self._session.add(row)
        await self._session.flush()
        revision = None
        if graph is not None:
            revision_row = BotGraphRevisionRow(
                bot_id=row.id,
                revision=FIRST_GRAPH_REVISION_NUMBER,
                graph=graph.model_dump(mode="json"),
            )
            self._session.add(revision_row)
            await self._session.flush()
            revision = self.revision_from_row(revision_row)
        await self._session.commit()
        await self._session.refresh(row)
        return self.read_from_row(row, revision)

    async def read(self, bot_id: UUID, *, lock: bool = False) -> BotRead | None:
        statement = select(BotRow).where(BotRow.id == bot_id)
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        return self.read_from_row(row, await self.latest_revision(bot_id))

    async def list(self) -> tuple[BotRead, ...]:
        rows = (
            await self._session.execute(
                select(BotRow).order_by(BotRow.updated_at.desc(), BotRow.id.desc())
            )
        ).scalars()
        return tuple(
            [
                self.read_from_row(row, await self.latest_revision(row.id))
                for row in rows
            ]
        )

    async def update_config(
        self,
        bot_id: UUID,
        config: PaperRunConfig,
    ) -> BotRead | None:
        statement = select(BotRow).where(BotRow.id == bot_id).with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            await self._session.commit()
            return None
        row.config = config.model_dump(mode="json")
        row.updated_at = system_now_utc()
        self._session.add(row)
        revision = await self.latest_revision(bot_id)
        await self._session.commit()
        await self._session.refresh(row)
        return self.read_from_row(row, revision)

    async def append_revision(
        self,
        bot_id: UUID,
        graph: NodeGraph,
    ) -> BotRead | None:
        # The row lock serializes revision numbering with config edits and run
        # snapshots, so every committed revision is one unique next version.
        bot_statement = select(BotRow).where(BotRow.id == bot_id).with_for_update()
        bot = (await self._session.execute(bot_statement)).scalar_one_or_none()
        if bot is None:
            await self._session.commit()
            return None
        latest_revision_number = await self._session.scalar(
            select(func.max(BotGraphRevisionRow.revision)).where(
                BotGraphRevisionRow.bot_id == bot_id
            )
        )
        row = BotGraphRevisionRow(
            bot_id=bot_id,
            revision=next_graph_revision_number(latest_revision_number),
            graph=graph.model_dump(mode="json"),
        )
        bot.updated_at = system_now_utc()
        self._session.add(bot)
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(bot)
        await self._session.refresh(row)
        return self.read_from_row(bot, self.revision_from_row(row))

    async def read_revision(
        self,
        bot_id: UUID,
        revision_id: UUID,
    ) -> BotGraphRevisionRead | None:
        row = (
            await self._session.execute(
                select(BotGraphRevisionRow).where(
                    BotGraphRevisionRow.bot_id == bot_id,
                    BotGraphRevisionRow.id == revision_id,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else self.revision_from_row(row)

    async def latest_revision(self, bot_id: UUID) -> BotGraphRevisionRead | None:
        row = (
            await self._session.execute(
                select(BotGraphRevisionRow)
                .where(BotGraphRevisionRow.bot_id == bot_id)
                .order_by(BotGraphRevisionRow.revision.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return None if row is None else self.revision_from_row(row)

    @staticmethod
    def read_from_row(
        row: BotRow,
        revision: BotGraphRevisionRead | None,
    ) -> BotRead:
        return BotRead(
            id=row.id,
            definition_id=row.definition_id,
            config=PaperRunConfig.model_validate(row.config),
            latest_graph_revision=revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def revision_from_row(row: BotGraphRevisionRow) -> BotGraphRevisionRead:
        return BotGraphRevisionRead(
            id=row.id,
            bot_id=row.bot_id,
            revision=row.revision,
            graph=NodeGraph.model_validate(row.graph),
            created_at=row.created_at,
        )
