from decimal import Decimal
from pathlib import Path

import pytest

from bots.framework.config import (
    BOT_API_KEY_ENV,
    BOT_API_PASSPHRASE_ENV,
    BOT_API_SECRET_ENV,
    BOT_BOOK_MAX_AGE_MS_ENV,
    BOT_FUNDER_ADDRESS_ENV,
    BOT_LIVE_ENABLED_ENV,
    BOT_STREAM_RULES_ENV,
    BOT_MAX_ORDER_SIZE_ENV,
    BOT_MAX_SLIPPAGE_PCT_ENV,
    BOT_MODE_ENV,
    BOT_PAPER_LATENCY_JITTER_MS_ENV,
    BOT_PAPER_LATENCY_MS_ENV,
    BOT_PAPER_PORTFOLIO_USDC_ENV,
    BOT_PRIVATE_KEY_ENV,
    BotConfig,
    BotMode,
    DEFAULT_BOT_MODE,
    DEFAULT_BOOK_MAX_AGE_MS,
    DEFAULT_MAX_ORDER_SIZE,
    DEFAULT_MAX_SLIPPAGE_PCT,
    DEFAULT_PAPER_LATENCY_JITTER_MS,
    DEFAULT_PAPER_LATENCY_MS,
    DEFAULT_PAPER_PORTFOLIO_USDC,
)


def test_config_reads_env_and_per_bot_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BOT_MODE_ENV, BotMode.LIVE.value)
    monkeypatch.setenv(
        BOT_STREAM_RULES_ENV,
        '[{"relation":"filtered","market_slugs":["btc-up","eth-up"],"wallet_addresses":["0x0000000000000000000000000000000000000001","0x0000000000000000000000000000000000000002"]}]',
    )
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
    assert config.stream_rules[0].market_slugs == ("btc-up", "eth-up")
    assert config.stream_rules[0].wallet_addresses == (
        "0x0000000000000000000000000000000000000001",
        "0x0000000000000000000000000000000000000002",
    )
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
    ("env_key", "default"),
    (
        (BOT_MODE_ENV, DEFAULT_BOT_MODE.value),
        (BOT_MAX_ORDER_SIZE_ENV, str(DEFAULT_MAX_ORDER_SIZE)),
        (BOT_MAX_SLIPPAGE_PCT_ENV, str(DEFAULT_MAX_SLIPPAGE_PCT)),
        (BOT_PAPER_LATENCY_MS_ENV, str(DEFAULT_PAPER_LATENCY_MS)),
        (BOT_PAPER_LATENCY_JITTER_MS_ENV, str(DEFAULT_PAPER_LATENCY_JITTER_MS)),
        (BOT_BOOK_MAX_AGE_MS_ENV, str(DEFAULT_BOOK_MAX_AGE_MS)),
        (BOT_PAPER_PORTFOLIO_USDC_ENV, str(DEFAULT_PAPER_PORTFOLIO_USDC)),
    ),
)
def test_author_guide_documents_runtime_defaults(env_key: str, default: str) -> None:
    guide = (Path(__file__).parents[1] / "docs" / "bot-author-guide.md").read_text()
    assert f"{env_key}={default}" in guide


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
