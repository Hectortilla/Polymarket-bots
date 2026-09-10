"""Saved-bot lifecycle failures shared by persistence and HTTP."""

BOT_ACTIVE_RUNS_DETAIL = (
    "Stop all active runs and wait for them to finish before deleting this bot."
)


class BotHasActiveRunsError(Exception):
    """A saved bot cannot be deleted while any run is nonterminal."""


class BotUnavailableError(Exception):
    """A run cannot be created from a missing or deleted saved bot."""
