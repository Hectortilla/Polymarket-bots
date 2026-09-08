from __future__ import annotations

from polybot.execution.broker import Broker
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.framework.events import FillEvent, OrderRequest


class LiveBroker(Broker):
    def __init__(self, config: BotConfig) -> None:
        if config.mode is not BotMode.LIVE or not config.live_enabled:
            raise RuntimeError("Live broker requires BOT_MODE=live and BOT_LIVE_ENABLED=true.")
        self._require_live_credentials(config)

    async def submit(self, order: OrderRequest) -> FillEvent:
        raise NotImplementedError("Implement CLOB signed order submission.")

    async def cancel_all(self) -> None:
        raise NotImplementedError("Implement authenticated CLOB cancel-all.")

    @staticmethod
    def _require_live_credentials(config: BotConfig) -> None:
        if not all(
            (
                config.private_key,
                config.api_key,
                config.api_secret,
                config.api_passphrase,
                config.funder_address,
            )
        ):
            raise RuntimeError("Live broker requires wallet, funder, and CLOB credentials.")
