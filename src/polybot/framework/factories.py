"""Public bot-factory contract and invocation policy."""

from collections.abc import Callable
import inspect

from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig


type BotFactory = Callable[[], BaseBot] | Callable[[BotConfig], BaseBot]
type BoundBotFactory = Callable[[BotConfig], BaseBot]


def bind_bot_factory(factory: BotFactory) -> BoundBotFactory:
    """Validate and normalize the public zero-or-one-config factory contract."""
    signature = inspect.signature(factory)
    if _accepts_arguments(signature, object()):
        return lambda config: _require_bot(factory(config))
    if _accepts_arguments(signature):
        return lambda config: _require_bot(factory())
    raise TypeError("bot factory must accept zero arguments or one BotConfig")


def _accepts_arguments(signature: inspect.Signature, *arguments: object) -> bool:
    try:
        signature.bind(*arguments)
    except TypeError:
        return False
    return True


def _require_bot(value: object) -> BaseBot:
    if not isinstance(value, BaseBot):
        raise TypeError("bot factory did not return BaseBot")
    return value
