"""Shared replay capability checks used by CLI and backtest services."""

from collections.abc import Iterable

from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.framework.streams import StreamRule

LIVE_BACKTEST_UNSUPPORTED_MESSAGE = "backtesting cannot run with BOT_MODE=live"
WALLET_REPLAY_UNSUPPORTED_MESSAGE = (
    "wallet stream rules cannot be replayed from a market-only archive"
)


def backtest_config_issue(config: BotConfig) -> str | None:
    return LIVE_BACKTEST_UNSUPPORTED_MESSAGE if config.mode is BotMode.LIVE else None


def replay_rule_issue(rules: Iterable[StreamRule]) -> str | None:
    return (
        WALLET_REPLAY_UNSUPPORTED_MESSAGE
        if any(rule.wallet_addresses for rule in rules)
        else None
    )
