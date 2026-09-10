"""Required global incident state; missing persistence never enables admission."""

from sqlalchemy.ext.asyncio import AsyncSession

from api.operations.models import OperationControlRow
from api.operations.schema import GLOBAL_OPERATION_CONTROL_ROW_ID, OperatorOutcome

MISSING_CONTROL_DETAIL = "required operation control is missing"


class OperationControlMissing(RuntimeError):
    def __init__(self) -> None:
        super().__init__(MISSING_CONTROL_DETAIL)


class OperationControlStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_admissions_paused(self, paused: bool) -> OperatorOutcome:
        control = await self.require()
        outcome = (
            OperatorOutcome.APPLIED
            if control.admissions_paused != paused
            else OperatorOutcome.UNCHANGED
        )
        control.admissions_paused = paused
        self._session.add(control)
        return outcome

    async def require(self) -> OperationControlRow:
        control = await self._session.get(
            OperationControlRow, GLOBAL_OPERATION_CONTROL_ROW_ID
        )
        if control is None:
            raise OperationControlMissing
        return control
