"""Catalog-owned bot construction and paper-runtime invocation."""

from polybot.runtime import run_bot
from polybot_control_plane.catalog.definitions import CATALOG
from polybot_control_plane.events.observer import WebRuntimeObserver
from polybot_control_plane.runs.contracts import RunRead


async def run_claimed_bot(run: RunRead, observer: WebRuntimeObserver) -> None:
    entry = CATALOG.get(run.definition_id)
    if entry is None or not entry.matches_version(run.definition_version):
        raise RuntimeError("catalog definition version is no longer available")
    bot_config = run.config.to_bot_config()
    await run_bot(
        entry.create_bot(bot_config),
        bot_config,
        observer=observer,
    )
