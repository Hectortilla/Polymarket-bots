"""Public bot-factory contract used by CLI and recording entrypoints."""

from collections.abc import Callable

from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig


type BotFactory = Callable[[], BaseBot] | Callable[[BotConfig], BaseBot]
