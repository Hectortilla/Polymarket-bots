import pytest

from bots.execution.live import LiveBroker
from bots.framework.config import BOT_MODE_ENV, BotConfig, BotMode

LIVE_MODE_REQUIREMENT = f"{BOT_MODE_ENV}={BotMode.LIVE.value}"


def test_live_broker_requires_live_mode_and_enabled_flag() -> None:
    with pytest.raises(RuntimeError, match=LIVE_MODE_REQUIREMENT):
        LiveBroker(
            BotConfig(
                name="paper",
                live_enabled=True,
                private_key="private",
                api_key="key",
                api_secret="secret",
                api_passphrase="passphrase",
                funder_address="0xfunder",
            )
        )

    with pytest.raises(RuntimeError, match=LIVE_MODE_REQUIREMENT):
        LiveBroker(BotConfig(name="disabled-live", mode=BotMode.LIVE))


def test_live_broker_accepts_explicit_live_gate() -> None:
    broker = LiveBroker(
        BotConfig(
            name="live",
            mode=BotMode.LIVE,
            live_enabled=True,
            private_key="private",
            api_key="key",
            api_secret="secret",
            api_passphrase="passphrase",
            funder_address="0xfunder",
        )
    )

    assert broker is not None


def test_live_broker_requires_credentials() -> None:
    with pytest.raises(RuntimeError, match="CLOB credentials"):
        LiveBroker(BotConfig(name="missing-secrets", mode=BotMode.LIVE, live_enabled=True))
