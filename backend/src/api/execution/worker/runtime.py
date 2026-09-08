"""Catalog-owned bot construction and paper-runtime invocation."""

from polybot.runtime import run_bot

from api.catalog.definitions import CATALOG
from api.events.observer import WebRuntimeObserver
from api.runs.contracts import RunRead


async def run_claimed_bot(run: RunRead, observer: WebRuntimeObserver) -> None:
    entry = CATALOG.get(run.definition_id)
    if entry is None:
        raise RuntimeError("catalog definition is no longer available")
    bot_config = run.config.to_bot_config()
    await run_bot(
        entry.create_bot(bot_config, run.graph),
        bot_config,
        observer=observer,
    )
