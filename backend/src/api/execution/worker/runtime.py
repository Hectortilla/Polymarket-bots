"""Catalog-owned bot construction and paper-runtime invocation."""

from contextlib import nullcontext

from polybot.execution.ownership import ExecutionScope
from polybot.runtime import run_bot

from api.catalog.definitions import CATALOG
from api.events.observer import WebRuntimeObserver
from api.limits.policy import PAPER_BETA
from api.runs.contracts import RunRead


async def run_claimed_bot(
    run: RunRead,
    observer: WebRuntimeObserver,
    *,
    execution_scope: ExecutionScope = nullcontext,
) -> None:
    entry = CATALOG.get(run.definition_id)
    if entry is None:
        raise RuntimeError("catalog definition is no longer available")
    bot_config = run.config.to_bot_config()
    await run_bot(
        entry.create_bot(bot_config, run.config.graph),
        bot_config,
        observer=observer,
        max_tracked_markets=PAPER_BETA.tracked_markets_per_run,
        execution_scope=execution_scope,
    )
