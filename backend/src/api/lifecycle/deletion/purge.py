"""Retry-safe removal follows event -> run -> revision -> bot -> identity order."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.access import AccountAccessStore
from api.bots.models import BotGraphRevisionRow, BotRow
from api.graph_templates.models import GraphTemplateRow
from api.lifecycle.deletion.models import DeletionRequestRow
from api.lifecycle.history.purge import TerminalHistoryPurger
from api.lifecycle.policy import (
    CLEANUP_ACCOUNT_BATCH_SIZE,
    CLEANUP_RUN_BATCH_SIZE,
    DELETION_QUIESCENCE_SECONDS,
)
from api.limits.admission import RunAdmission
from api.runs.models import RunRow


class AccountPurger:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def clean(self, now: datetime) -> int:
        await RunAdmission(self._session).lock_transaction()
        receipts = (
            await self._session.scalars(
                select(DeletionRequestRow)
                .where(
                    DeletionRequestRow.completed_at.is_(None),
                    DeletionRequestRow.requested_at
                    <= now - timedelta(seconds=DELETION_QUIESCENCE_SECONDS),
                )
                .order_by(DeletionRequestRow.requested_at, DeletionRequestRow.user_id)
                .limit(CLEANUP_ACCOUNT_BATCH_SIZE)
                .with_for_update()
            )
        ).all()
        completed_account_count = 0
        for receipt in receipts:
            if await self._purge_account(receipt.user_id, now):
                receipt.completed_at = now
                self._session.add(receipt)
                completed_account_count += 1
        await self._session.commit()
        return completed_account_count

    async def _purge_account(self, user_id: UUID, now: datetime) -> bool:
        account = await AccountAccessStore(self._session).lock_account(user_id)
        if account is None:
            return True
        owned_bot_ids_query = select(BotRow.id).where(BotRow.owner_user_id == user_id)
        run_ids = (
            await self._session.scalars(
                select(RunRow.id)
                .where(RunRow.bot_id.in_(owned_bot_ids_query))
                .order_by(RunRow.id)
                .limit(CLEANUP_RUN_BATCH_SIZE)
            )
        ).all()
        purger = TerminalHistoryPurger(self._session)
        for run_id in run_ids:
            await purger.purge(run_id, now)
        await self._session.flush()
        if (
            await self._session.scalar(
                select(RunRow.id).where(RunRow.bot_id.in_(owned_bot_ids_query)).limit(1)
            )
            is not None
        ):
            return False
        await self._session.execute(
            delete(BotGraphRevisionRow).where(
                BotGraphRevisionRow.bot_id.in_(owned_bot_ids_query)
            )
        )
        await self._session.execute(
            delete(BotRow).where(BotRow.owner_user_id == user_id)
        )
        await self._session.execute(
            delete(GraphTemplateRow).where(GraphTemplateRow.owner_user_id == user_id)
        )
        await AccountAccessStore(self._session).invalidate_credentials(user_id)
        await self._session.delete(account)
        return True
