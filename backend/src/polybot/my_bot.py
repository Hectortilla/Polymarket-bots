"""Default CLI factory for the BTC five-minute momentum example."""

from polybot.examples.example_dynamic_random_hold import (
    create as create_btc_momentum,
)
from polybot.framework.config.models import BotConfig


def create(_config: BotConfig):
    return create_btc_momentum()
