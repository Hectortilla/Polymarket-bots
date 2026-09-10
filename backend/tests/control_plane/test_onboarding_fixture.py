"""Fixture contract, routing and managed delivery failure coverage."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from api.runs.failures import RunSnapshotError
from polybot.framework.clock import Clock
from polybot.framework.config.models import BotConfig
from polybot.framework.streams import StreamRelation, StreamRule

from control_plane import browser_launcher
from control_plane.browser_launcher import BrowserRunLauncher
from control_plane.onboarding_browser_contract import (
    ONBOARDING_BROWSER_CONTRACT_PATH,
    onboarding_browser_contract,
)
from control_plane.onboarding_fixture.market_data import OnboardingMarketData
from control_plane.onboarding_fixture.selection import onboarding_case
from control_plane.onboarding_policy import ONBOARDING_CASES, OnboardingScenario


def config_for(*slugs):
    return BotConfig(
        name="onboarding fixture",
        stream_rules=(
            StreamRule(relation=StreamRelation.INDEPENDENT, market_slugs=slugs),
        )
        if slugs
        else (),
    )


def test_browser_cases_match_the_owned_fixture_contract():
    assert (
        json.loads(ONBOARDING_BROWSER_CONTRACT_PATH.read_text())
        == onboarding_browser_contract()
    )


def test_fixture_selection_requires_exactly_one_supported_market():
    cases = tuple(ONBOARDING_CASES.values())
    for case in cases:
        assert onboarding_case(config_for(case.market_slug)) == case
    for slugs in (
        (),
        ("ordinary-market",),
        ("ordinary-market", cases[0].market_slug),
        tuple(case.market_slug for case in cases),
    ):
        assert onboarding_case(config_for(*slugs)) is None


def test_fixture_books_use_explicit_clock_and_matching_outcome():
    async def scenario():
        clock = Mock(spec=Clock)
        clock.now_ms.return_value = 1234
        for case in ONBOARDING_CASES.values():
            source = OnboardingMarketData(case, clock)
            for outcome in source.market.outcomes:
                book = await source.latest(outcome.token_id)
                assert book.received_at_ms == clock.now_ms.return_value
                assert book.outcome == outcome.label
                assert book.best_ask.price == case.ask
            assert await source.latest("unknown-token") is None
            assert await source.find_by_slug("unknown-market") is None

    asyncio.run(scenario())


def test_launcher_recovery_retries_task_failure_deduplicates_and_drains_shutdown(
    caplog,
):
    async def scenario():
        sessions = Mock(return_value=AsyncMock())
        launcher = BrowserRunLauncher(AsyncMock(), sessions)
        run_id = uuid4()
        config = config_for(ONBOARDING_CASES[OnboardingScenario.ACTION].market_slug)
        store = AsyncMock()
        store.read.return_value = SimpleNamespace(
            config=SimpleNamespace(to_bot_config=lambda: config)
        )
        recovered = asyncio.Event()
        stopped = asyncio.Event()
        executions = 0

        async def execute(_run_id):
            nonlocal executions
            executions += 1
            if executions == 1:
                raise ConnectionError("fixture database failure")
            recovered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def recovery_tick():
            await launcher.launch(run_id)

        launcher.recovery.tick = AsyncMock(side_effect=recovery_tick)
        coordinator = Mock(execute=AsyncMock(side_effect=execute))

        @asynccontextmanager
        async def original_lifespan(_app):
            yield

        app = SimpleNamespace(
            router=SimpleNamespace(lifespan_context=original_lifespan)
        )
        launcher.install_lifespan(app)
        with (
            patch.object(browser_launcher, "RunStore", return_value=store),
            patch.object(
                browser_launcher, "RunLifecycleCoordinator", return_value=coordinator
            ),
        ):
            async with app.router.lifespan_context(app):
                await asyncio.wait_for(recovered.wait(), timeout=2)
                await launcher.launch(run_id)
                assert executions == 2
            assert stopped.is_set()
            assert launcher.execution_tasks_by_run_id == {}
        assert launcher.recovery.tick.await_count >= 2

    asyncio.run(scenario())
    assert "durable recovery will retry or interrupt" in caplog.text


def test_missing_delivery_state_is_explicit_and_corrupt_snapshot_reaches_coordinator():
    async def scenario():
        launcher = BrowserRunLauncher(AsyncMock(), Mock(return_value=AsyncMock()))
        store = AsyncMock()
        store.read.return_value = None
        coordinator = Mock(execute=AsyncMock())
        with (
            patch.object(browser_launcher, "RunStore", return_value=store),
            patch.object(
                browser_launcher, "RunLifecycleCoordinator", return_value=coordinator
            ),
        ):
            with pytest.raises(LookupError, match="persisted run"):
                await launcher.launch(uuid4())
            store.read.side_effect = RunSnapshotError("corrupt snapshot")
            await launcher.launch(uuid4())
            await asyncio.gather(*launcher.execution_tasks_by_run_id.values())
            coordinator.execute.assert_awaited_once()

    asyncio.run(scenario())
