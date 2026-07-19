"""Bot factory loading for the CLI."""

from __future__ import annotations

import importlib
import inspect
from typing import cast

from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.factories import BotFactory


def load_bot(spec: str, config: BotConfig) -> BaseBot:
    try:
        module_name, attribute = spec.split(":", 1)
        factory = getattr(importlib.import_module(module_name), attribute)
    except (ValueError, ImportError, AttributeError) as error:
        raise ValueError(f"invalid bot factory: {spec}") from error
    if isinstance(factory, BaseBot):
        return factory
    if not callable(factory):
        raise TypeError(f"bot factory is not callable: {spec}")
    bot_factory = cast(BotFactory, factory)
    signature = inspect.signature(bot_factory)
    bot = (
        bot_factory(config)
        if _accepts_one_argument(signature)
        else bot_factory()
    )
    if not isinstance(bot, BaseBot):
        raise TypeError(f"bot factory did not return BaseBot: {spec}")
    return bot


def _accepts_one_argument(signature: inspect.Signature) -> bool:
    try:
        signature.bind(object())
    except TypeError:
        return False
    return True
