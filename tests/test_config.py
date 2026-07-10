from decimal import Decimal

import pytest

from bots.framework.config import (
    BOT_API_KEY_ENV,
    BOT_API_PASSPHRASE_ENV,
    BOT_API_SECRET_ENV,
    BOT_BOOK_MAX_AGE_MS_ENV,
    BOT_FUNDER_ADDRESS_ENV,
    BOT_LIVE_ENABLED_ENV,
    BOT_MARKET_SLUGS_ENV,
    BOT_MAX_ORDER_SIZE_ENV,
    BOT_MAX_SLIPPAGE_PCT_ENV,
    BOT_MODE_ENV,
    BOT_PAPER_LATENCY_JITTER_MS_ENV,
    BOT_PAPER_LATENCY_MS_ENV,
    BOT_PAPER_PORTFOLIO_USDC_ENV,
    BOT_PRIVATE_KEY_ENV,
    BOT_WALLET_ADDRESSES_ENV,
    BotConfig,
    BotMode,
    DEFAULT_BOOK_MAX_AGE_MS,
)


def test_config_reads_env_and_per_bot_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BOT_MODE_ENV, BotMode.LIVE.value)
    monkeypatch.setenv(BOT_MARKET_SLUGS_ENV, "btc-up, eth-up")
    monkeypatch.setenv(BOT_WALLET_ADDRESSES_ENV, "0xleader1, 0xleader2")
    monkeypatch.setenv(BOT_MAX_ORDER_SIZE_ENV, "4")
    monkeypatch.setenv(BOT_MAX_SLIPPAGE_PCT_ENV, "0.01")
    monkeypatch.setenv(BOT_PAPER_LATENCY_MS_ENV, "300")
    monkeypatch.setenv(BOT_PAPER_LATENCY_JITTER_MS_ENV, "50")
    monkeypatch.setenv(BOT_BOOK_MAX_AGE_MS_ENV, str(DEFAULT_BOOK_MAX_AGE_MS))
    monkeypatch.setenv(BOT_PAPER_PORTFOLIO_USDC_ENV, "500")
    monkeypatch.setenv(BOT_LIVE_ENABLED_ENV, "true")
    monkeypatch.setenv(BOT_PRIVATE_KEY_ENV, "private")
    monkeypatch.setenv(BOT_API_KEY_ENV, "key")
    monkeypatch.setenv(BOT_API_SECRET_ENV, "secret")
    monkeypatch.setenv(BOT_API_PASSPHRASE_ENV, "passphrase")
    monkeypatch.setenv(BOT_FUNDER_ADDRESS_ENV, "0xfunder")

    config = BotConfig.from_env("env-bot").with_overrides(max_order_size=Decimal("2"))

    assert config.mode is BotMode.LIVE
    assert config.market_slugs == ("btc-up", "eth-up")
    assert config.wallet_addresses == ("0xleader1", "0xleader2")
    assert config.max_order_size == Decimal("2")
    assert config.max_slippage_pct == Decimal("0.01")
    assert config.paper_latency_ms == 300
    assert config.paper_latency_jitter_ms == 50
    assert config.book_max_age_ms == DEFAULT_BOOK_MAX_AGE_MS
    assert config.paper_portfolio_usdc == Decimal("500")
    assert config.live_enabled is True
    assert config.private_key == "private"
    assert config.api_key == "key"
    assert config.api_secret == "secret"
    assert config.api_passphrase == "passphrase"
    assert config.funder_address == "0xfunder"


def test_config_rejects_invalid_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BOT_MODE_ENV, "demo")

    with pytest.raises(ValueError):
        BotConfig.from_env("bad-mode")


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"max_order_size": Decimal("0")}, "max_order_size"),
        ({"max_slippage_pct": Decimal("-0.01")}, "max_slippage_pct"),
        ({"paper_latency_ms": -1}, "paper_latency_ms"),
        ({"paper_latency_jitter_ms": -1}, "paper_latency_jitter_ms"),
        ({"book_max_age_ms": -1}, "book_max_age_ms"),
        ({"paper_portfolio_usdc": Decimal("0")}, "paper_portfolio_usdc"),
    ),
)
def test_config_rejects_invalid_ranges(
    override: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        BotConfig(name="invalid", **override)  # type: ignore[arg-type]
