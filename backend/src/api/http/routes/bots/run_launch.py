"""Saved-bot run snapshot and delivery endpoint."""

import asyncio
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status

from api.auth.dependencies import CurrentUserDependency
from api.auth.recovery.policy import VERIFICATION_REQUIRED_DETAIL
from api.bots.store import BotStore
from api.http.contracts import ErrorResponse, RequestValidationFailure
from api.http.dependencies import (
    LauncherDependency,
    SessionFactoryDependency,
)
from api.http.protocol import IDEMPOTENCY_KEY_HEADER
from api.http.responses import NOT_FOUND_AND_CONFLICT_RESPONSES
from api.http.routes.bots.validation import (
    require_bot,
    require_catalog_entry,
    require_run_revision_contract,
)
from api.http.routes.paths import (
    BOT_RUNS_PATH,
    LAUNCH_BOT_RUN_OPERATION_ID,
)
from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.runs.contracts import RunRead
from api.runs.store import RunStore

LOGGER = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    BOT_RUNS_PATH,
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id=LAUNCH_BOT_RUN_OPERATION_ID,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        **NOT_FOUND_AND_CONFLICT_RESPONSES,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse | RequestValidationFailure
        },
    },
)
async def launch_bot_run(
    bot_id: UUID,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
    launcher: LauncherDependency,
    launch_key: Annotated[UUID | None, Header(alias=IDEMPOTENCY_KEY_HEADER)] = None,
) -> RunRead:
    async with session_factory() as session:
        if not user.can_launch_runs:
            raise HTTPException(status.HTTP_403_FORBIDDEN, VERIFICATION_REQUIRED_DETAIL)
        # The lock makes the committed run snapshot atomic with config and
        # revision edits; delivery starts only after that transaction commits.
        bot = require_bot(await BotStore(session, user.id).read(bot_id, lock=True))
        store = RunStore(session)
        existing = (
            None if launch_key is None else await store.read_launch(bot.id, launch_key)
        )
        if existing is not None:
            return existing
        definition = require_catalog_entry(bot.definition_id)
        require_run_revision_contract(definition, bot)
        bot.config.require_subscription_allowance()
        run = await store.create_from_bot(bot, launch_key=launch_key)
    try:
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            await launcher.launch(run.id)
    except Exception:
        # The committed queue row is the delivery obligation, even if the API
        # dies here or Redis accepted the hint before the response was lost.
        LOGGER.warning("run delivery hint unavailable; queued run awaits recovery")
    return run
