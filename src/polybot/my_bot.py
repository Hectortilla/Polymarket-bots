"""Default CLI factory for the BTC five-minute momentum example."""

from polybot.examples.example_btc_five_minute_momentum import (
    BtcFiveMinuteMomentumBot,
    create as create_btc_momentum,
)
from polybot.framework.config.models import BotConfig


def create(_config: BotConfig) -> BtcFiveMinuteMomentumBot:
    return create_btc_momentum()
