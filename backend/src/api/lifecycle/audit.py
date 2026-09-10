"""Bounded expiry of operator audits and completed deletion receipts."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.lifecycle.deletion.models import DeletionRequestRow
from api.lifecycle.policy import CLEANUP_AUDIT_BATCH_SIZE, OPERATOR_AUDIT_RETENTION_DAYS
from api.operations.models import OperatorAuditRow


class AuditRetention:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def clean(self, now: datetime) -> None:
        cutoff = now - timedelta(days=OPERATOR_AUDIT_RETENTION_DAYS)
        expired_audit_ids_query = (
            select(OperatorAuditRow.id)
            .where(OperatorAuditRow.occurred_at <= cutoff)
            .order_by(OperatorAuditRow.occurred_at)
            .limit(CLEANUP_AUDIT_BATCH_SIZE)
        )
        await self._session.execute(
            delete(OperatorAuditRow).where(
                OperatorAuditRow.id.in_(expired_audit_ids_query)
            )
        )
        completed_deletion_user_ids_query = (
            select(DeletionRequestRow.user_id)
            .where(DeletionRequestRow.completed_at <= cutoff)
            .order_by(DeletionRequestRow.completed_at)
            .limit(CLEANUP_AUDIT_BATCH_SIZE)
        )
        await self._session.execute(
            delete(DeletionRequestRow).where(
                DeletionRequestRow.user_id.in_(completed_deletion_user_ids_query)
            )
        )
        await self._session.commit()
