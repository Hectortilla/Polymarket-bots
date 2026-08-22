"""Bot factory loading for the CLI."""

from __future__ import annotations

import importlib
from typing import cast

from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.factories import BotFactory, bind_bot_factory


INVALID_BOT_FACTORY_PREFIX = "invalid bot factory"


def load_bot(spec: str, config: BotConfig) -> BaseBot:
    try:
        module_name, attribute = spec.split(":", 1)
        factory = getattr(importlib.import_module(module_name), attribute)
    except (ValueError, ImportError, AttributeError) as error:
        raise ValueError(_invalid_bot_factory_message(spec)) from error
    if isinstance(factory, BaseBot):
        return factory
    if not callable(factory):
        raise TypeError(f"bot factory is not callable: {spec}")
    bot_factory = cast(BotFactory, factory)
    try:
        return bind_bot_factory(bot_factory)(config)
    except TypeError as error:
        raise TypeError(_invalid_bot_factory_message(spec, str(error))) from error


def _invalid_bot_factory_message(spec: str, detail: str | None = None) -> str:
    message = f"{INVALID_BOT_FACTORY_PREFIX}: {spec}"
    return message if detail is None else f"{message}: {detail}"
