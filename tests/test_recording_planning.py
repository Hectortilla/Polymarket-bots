from __future__ import annotations

import asyncio
import json

import pytest

from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.recording.clock import ObservationClock
from polybot.recording.duration import parse_duration_seconds
from polybot.recording.identity import bot_target_identity, static_target_identity
from polybot.recording.planning import (
    BotStreamPlanProvider,
    ORDERING_DISABLED_MESSAGE,
    RejectingRecordingBroker,
    StaticStreamPlanProvider,
    WALLET_ACTIVITY_DISABLED_MESSAGE,
    planning_context,
)


class DynamicPlanBot(BaseBot):
    async def current_stream_rules(self, ctx, now_ms):
        return (
            StreamRule(
                StreamRelation.INDEPENDENT,
                market_slugs=(f"current-{now_ms}",),
            ),
        )

    async def next_stream_rules(self, ctx, now_ms):
        return (
            StreamRule(
                StreamRelation.INDEPENDENT,
                market_slugs=(f"next-{now_ms}",),
            ),
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    (("1s", 1), ("2m", 120), ("3h", 10_800), ("10d", 864_000)),
)
def test_parse_recording_duration(value: str, expected: int) -> None:
    assert parse_duration_seconds(value) == expected


@pytest.mark.parametrize("value", ("", "0s", "1", "1w", "-1h", "one-day"))
def test_parse_recording_duration_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_duration_seconds(value)


def test_observation_clock_uses_monotonic_elapsed_time() -> None:
    monotonic_values = iter((5_000_000_000, 5_125_000_000, 5_500_000_000))
    clock = ObservationClock(
        unix_time_ns=lambda: 1_700_000_000_000_000_000,
        monotonic_ns=lambda: next(monotonic_values),
    )

    assert clock.now_ms() == 1_700_000_000_125
    assert clock.now_ms() == 1_700_000_000_500


def test_observation_clock_can_continue_a_resumed_archive_floor() -> None:
    monotonic_values = iter((0, 1_000_000, 2_000_000))
    clock = ObservationClock(
        unix_time_ns=lambda: 1_000_000_000,
        monotonic_ns=lambda: next(monotonic_values),
    )

    clock.advance_to(2_000)

    assert clock.now_ms() == 2_000
    assert clock.now_ms() == 2_000


def test_static_plan_normalizes_and_deduplicates_slugs() -> None:
    provider = StaticStreamPlanProvider((" btc ", "eth", "btc", ""))

    plan = asyncio.run(provider.plan(1_000))

    assert plan.current_market_slugs == ("btc", "eth")
    assert plan.next == ()


def test_bot_plan_provider_calls_only_stream_rule_hooks(dummy_context) -> None:
    bot = DynamicPlanBot()
    provider = BotStreamPlanProvider(bot, dummy_context)

    plan = asyncio.run(provider.plan(1_234))

    assert plan.current_market_slugs == ("current-1234",)
    assert plan.next_market_slugs == ("next-1234",)


def test_recording_broker_rejects_ordering() -> None:
    broker = RejectingRecordingBroker()

    with pytest.raises(RuntimeError, match=ORDERING_DISABLED_MESSAGE):
        asyncio.run(broker.cancel_all())


def test_planning_context_rejects_wallet_data_queries() -> None:
    context = planning_context(
        BotConfig(name="recorder"),
        markets=object(),  # type: ignore[arg-type]
        books=object(),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match=WALLET_ACTIVITY_DISABLED_MESSAGE):
        asyncio.run(context.wallet_activity.latest_trades("0xwallet", 1))


def test_static_plan_requires_a_market() -> None:
    with pytest.raises(ValueError, match="at least one market slug"):
        StaticStreamPlanProvider(())


def test_target_identity_is_canonical_and_excludes_credentials() -> None:
    config = BotConfig(
        name="recorder",
        stream_rules=(
            StreamRule(StreamRelation.INDEPENDENT, market_slugs=("btc",)),
        ),
        private_key="secret-key",
        api_secret="secret-api-value",
    )

    identity = bot_target_identity("example:create", config)

    parsed = json.loads(identity)
    assert parsed["kind"] == "bot"
    assert parsed["spec"] == "example:create"
    assert parsed["config"]["stream_rules"] == [
        {
            "market_slugs": ["btc"],
            "relation": "independent",
            "wallet_addresses": [],
        }
    ]
    assert "secret" not in identity
    assert static_target_identity(("btc", "eth")) == (
        '{"kind":"static","market_slugs":["btc","eth"]}'
    )
    assert static_target_identity(("eth", "btc")) == static_target_identity(
        ("btc", "eth")
    )
