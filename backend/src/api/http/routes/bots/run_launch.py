"""Saved-bot run snapshot and delivery endpoint."""

from uuid import UUID

from fastapi import APIRouter, status
from polybot.framework.clock import system_now_utc

from api.auth.dependencies import CurrentUserDependency
from api.bots.store import BotStore
from api.events.writer import publish_durable_wake
from api.http.dependencies import (
    LauncherDependency,
    RedisDependency,
    SessionFactoryDependency,
)
from api.http.lifecycle import ApiRunLifecycle
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
from api.runs.contracts import RunRead
from api.runs.failures import sanitized_failure_detail
from api.runs.store import RunStore

RUN_LAUNCH_FAILURE_REASON = "run launch failed"

router = APIRouter()


@router.post(
    BOT_RUNS_PATH,
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id=LAUNCH_BOT_RUN_OPERATION_ID,
    responses=NOT_FOUND_AND_CONFLICT_RESPONSES,
)
async def launch_bot_run(
    bot_id: UUID,
    session_factory: SessionFactoryDependency,
    user: CurrentUserDependency,
    redis: RedisDependency,
    launcher: LauncherDependency,
) -> RunRead:
    async with session_factory() as session:
        # The lock makes the committed run snapshot atomic with config and
        # revision edits; delivery starts only after that transaction commits.
        bot = require_bot(await BotStore(session, user.id).read(bot_id, lock=True))
        definition = require_catalog_entry(bot.definition_id)
        require_run_revision_contract(definition, bot)
        run = await RunStore(session).create_from_bot(bot)
    try:
        await launcher.launch(run.id)
    except Exception as error:
        now = system_now_utc()
        async with session_factory() as session:
            run, event_id = await ApiRunLifecycle(session).fail_launch(
                run.id,
                now=now,
                failure_detail=sanitized_failure_detail(
                    error,
                    RUN_LAUNCH_FAILURE_REASON,
                ),
            )
        await publish_durable_wake(redis, run.id, event_id)
    return run
