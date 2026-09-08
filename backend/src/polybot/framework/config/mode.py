"""Bot execution mode contract."""

from enum import StrEnum


class BotMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"
