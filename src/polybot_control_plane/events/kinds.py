"""Dependency-light durable-event discriminators."""

from enum import StrEnum


EVENT_DISCRIMINATOR_FIELD = "kind"


class EventKind(StrEnum):
    RUN_LIFECYCLE = "run.lifecycle"
    RUN_BOOTSTRAP = "run.bootstrap"
    BOT_ACTIVITY = "bot.activity"
    BROKER_ORDER = "broker.order"
    BROKER_FILL = "broker.fill"
    BROKER_FAILURE = "broker.failure"
    MARKET_SETTLEMENT = "market.settlement"
    PORTFOLIO_SNAPSHOT = "portfolio.snapshot"
    WALLET_TIMELINE = "wallet.timeline"
    STREAM_HEALTH = "stream.health"
    RUN_FAILURE = "run.failure"
    CHART_SAMPLE = "chart.sample"


class LiveEventKind(StrEnum):
    CHART_MARKET = "chart.market"
    CHART_EQUITY = "chart.equity"
    CHART_WALLET = "chart.wallet"
    STREAM_HEALTH = "stream.health.live"
