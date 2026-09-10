"""Operator journal persistence participates in the enclosing mutation transaction."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.operations.models import OperatorAuditRow
from api.operations.schema import OperatorAction, OperatorOutcome


class OperatorAuditStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        actor: str,
        action: OperatorAction,
        target: UUID | None,
        outcome: OperatorOutcome,
    ) -> None:
        self._session.add(
            OperatorAuditRow(actor=actor, action=action, target=target, outcome=outcome)
        )
