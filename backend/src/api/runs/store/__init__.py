"""Async persistence boundary for durable paper-run lifecycle state."""

from copy import deepcopy
from datetime import datetime
from uuid import UUID, uuid4

from polybot.framework.clock import system_now_utc
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.bots.contracts import BotRead
from api.bots.errors import BotUnavailableError
from api.bots.models import BotRow
from api.lifecycle.history.selection import HistorySelection
from api.limits.admission import RunAdmission
from api.runs.contracts import ClaimedRunRead, RunRead
from api.runs.failures import (
    LaunchAttemptUnavailable,
    RunSnapshotError,
)
from api.runs.lease import ExecutionLease
from api.runs.models import RunRow
from api.runs.status import (
    INTERRUPTIBLE_RUN_STATUSES,
    QUEUED_PREVIOUS_STATUSES,
    TERMINAL_RUN_STATUSES,
    RunStatus,
)
from api.runs.terminal import TerminalRunWriter

from .owned import OwnedRunStore
from .transitions import RunTransitions


class RunStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.transitions = RunTransitions(session)

    def owned_by(self, lease: ExecutionLease) -> "OwnedRunStore":
        return OwnedRunStore(self, self._session, lease)

    async def read_launch(self, bot_id: UUID, launch_key: UUID) -> RunRead | None:
        result = (
            await self._session.execute(
                select(RunRow, BotRow.owner_user_id)
                .join(BotRow, BotRow.id == RunRow.bot_id)
                .where(RunRow.bot_id == bot_id, RunRow.launch_key == launch_key)
            )
        ).one_or_none()
        if result is None:
            return None
        row, owner_user_id = result
        if row.status in TERMINAL_RUN_STATUSES:
            retained_run_id = await self._session.scalar(
                select(RunRow.id).where(
                    RunRow.id == row.id, self._visible_history_predicate(owner_user_id)
                )
            )
            if retained_run_id is None:
                raise LaunchAttemptUnavailable
        return await self.read_row(row)

    async def recover_existing_launch(self, bot_id: UUID, launch_key: UUID) -> RunRead:
        await RunAdmission(self._session).lock_transaction()
        existing = await self.read_launch(bot_id, launch_key)
        if existing is None:
            raise LaunchAttemptUnavailable
        return existing

    async def create_from_bot(
        self,
        bot: BotRead,
        *,
        launch_key: UUID | None = None,
    ) -> RunRead:
        saved_bot = await self._session.scalar(
            select(BotRow)
            .where(BotRow.id == bot.id, BotRow.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if saved_bot is None:
            raise BotUnavailableError
        await RunAdmission(self._session).lock_transaction()
        if launch_key is not None:
            existing = await self.read_launch(bot.id, launch_key)
            if existing is not None:
                await self._session.commit()
                return existing
        await RunAdmission(self._session).require_queue_capacity(bot.id)
        # Persist the exact saved document under the same lock used by edits.
        # Copy nested graph values too; queued workers must never read bot config.
        row = RunRow(
            bot_id=bot.id,
            launch_key=launch_key,
            definition_id=saved_bot.definition_id,
            config_snapshot=deepcopy(saved_bot.config),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return RunRead.from_row(row)

    async def read(self, run_id: UUID) -> RunRead | None:
        row = await self._session.get(RunRow, run_id)
        return None if row is None else await self.read_row(row)

    async def read_owned(self, run_id: UUID, owner_user_id: UUID) -> RunRead | None:
        row = (
            await self._session.execute(
                self._owned_runs_statement(owner_user_id).where(
                    RunRow.id == run_id, self._visible_history_predicate(owner_user_id)
                )
            )
        ).scalar_one_or_none()
        return None if row is None else await self.read_row(row)

    async def list_owned(self, owner_user_id: UUID) -> tuple[RunRead, ...]:
        rows = (
            await self._session.execute(
                self._owned_runs_statement(owner_user_id)
                .where(self._visible_history_predicate(owner_user_id))
                .order_by(RunRow.created_at.desc(), RunRow.id.desc())
            )
        ).scalars()
        return tuple([await self.read_row(row) for row in rows])

    async def list(self) -> tuple[RunRead, ...]:
        statement = select(RunRow).order_by(
            RunRow.created_at.desc(),
            RunRow.id.desc(),
        )
        rows = (await self._session.execute(statement)).scalars()
        return tuple([await self.read_row(row) for row in rows])

    async def claim(self, run_id: UUID, *, now: datetime) -> ClaimedRunRead | None:
        if await RunAdmission(self._session).next_eligible_queued_run_id() != run_id:
            await self._session.commit()
            return None
        # The advisory lock serializes claims; the status predicate is the final
        # guard against stale deliveries.
        statement = (
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status == RunStatus.QUEUED)
            .values(
                status=RunStatus.STARTING,
                started_at=now,
                heartbeat_at=now,
                execution_token=uuid4(),
            )
            .returning(RunRow)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            await self._session.commit()
            return None
        try:
            claimed = ClaimedRunRead(
                **dict(await self.read_row(row)),
                execution_token=row.execution_token,
            )
        except Exception:
            await self._session.rollback()
            raise
        await self._session.commit()
        return claimed

    async def mark_running(self, run_id: UUID) -> bool:
        return await self.transitions.commit(run_id, RunStatus.RUNNING)

    async def begin_stopping(self, run_id: UUID) -> bool:
        return await self.transitions.commit(run_id, RunStatus.STOPPING)

    async def request_stop(self, run_id: UUID, *, now: datetime) -> RunStatus | None:
        transition = await self.transitions.request_stop_transition(run_id, now=now)
        if transition.applied_status is RunStatus.STOPPED:
            await TerminalRunWriter(self._session).commit(transition.row)
        else:
            await self._session.commit()
        return None if transition.row is None else transition.row.status

    async def heartbeat(self, run_id: UUID, *, now: datetime) -> bool:
        result = await self._session.execute(
            update(RunRow)
            .where(
                RunRow.id == run_id,
                RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES),
            )
            .values(heartbeat_at=now)
        )
        await self._session.commit()
        return result.rowcount == 1

    async def status(self, run_id: UUID) -> RunStatus | None:
        row = await self._session.get(RunRow, run_id)
        return None if row is None else row.status

    async def fail_queued(
        self, run_id: UUID, *, now: datetime, failure_detail: str
    ) -> bool:
        return await self.transitions.commit(
            run_id,
            RunStatus.FAILED,
            expected_statuses=QUEUED_PREVIOUS_STATUSES,
            ended_at=now,
            failure_detail=failure_detail,
        )

    async def finish(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        now: datetime,
        failure_detail: str | None = None,
        execution_lease: ExecutionLease | None = None,
    ) -> bool:
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError("finish requires a terminal run status")
        expected_statuses = (
            frozenset({RunStatus.STOPPING}) if status is RunStatus.STOPPED else None
        )
        return await self.transitions.commit(
            run_id,
            status,
            expected_statuses=expected_statuses,
            ended_at=now,
            failure_detail=failure_detail,
            execution_lease=execution_lease,
        )

    async def interrupt_expired(
        self,
        run_id: UUID,
        *,
        expired_before: datetime,
        now: datetime,
    ) -> bool:
        return await self.transitions.commit(
            run_id,
            RunStatus.INTERRUPTED,
            expired_before=expired_before,
            ended_at=now,
        )

    async def read_row(self, row: RunRow) -> RunRead:
        bot = await self._session.get(BotRow, row.bot_id)
        if bot is None:
            raise RunSnapshotError("run bot is missing")
        return RunRead.from_row(row).model_copy(
            update={"bot_deleted": bot.deleted_at is not None}
        )

    @staticmethod
    def _visible_history_predicate(owner_user_id: UUID):
        return or_(
            RunRow.status.not_in(TERMINAL_RUN_STATUSES),
            RunRow.id.in_(
                HistorySelection(system_now_utc()).retained_run_ids_query(owner_user_id)
            ),
        )

    @staticmethod
    def _owned_runs_statement(owner_user_id: UUID):
        return (
            select(RunRow)
            .join(BotRow, BotRow.id == RunRow.bot_id)
            .where(BotRow.owner_user_id == owner_user_id)
        )
