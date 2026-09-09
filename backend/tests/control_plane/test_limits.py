"""Shared-service acceptance for the Slice 17 paper-beta allowance boundary."""

import asyncio
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import api.execution.worker.lifecycle as lifecycle
import pytest
from api.auth.config import AuthSettings
from api.auth.contracts import CurrentUser
from api.auth.dependencies import application_authentication
from api.bots.store import BotStore
from api.catalog.definitions import CATALOG, WINNER_DEFINITION_ID
from api.catalog.graphs.starter import STARTER_NODE_GRAPH
from api.events.writer import RunEventWriter
from api.execution.worker.lifecycle import (
    DURATION_EXPIRED_DETAIL,
    RunLifecycleCoordinator,
)
from api.graph_templates.contracts import GraphTemplateCreate
from api.graph_templates.store import GraphTemplateStore
from api.http.app import create_app
from api.http.lifecycle import ApiRunLifecycle
from api.http.routes.paths import BOT_RUNS_PATH, USAGE_PATH, api_route_path
from api.limits.admission import RunAdmission
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.limits.policy import PAPER_BETA
from api.limits.redis.request_budgets import RequestRateLimiter
from api.limits.redis.stream_admission import OpenStreamAdmission
from api.limits.usage import AccountUsageReader
from api.runs.status import RunStatus
from api.runs.store import RunStore
from fastapi import Request, status
from httpx import ASGITransport, AsyncClient
from polybot.cli.tracked_markets import (
    MarketInterest,
    TrackedMarketLimitExceeded,
    TrackedMarketRegistry,
)
from polybot.framework.clock import system_now_utc
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.polymarket.markets import Market, MarketOutcome
from redis.exceptions import ConnectionError as RedisConnectionError

from control_plane.auth_fixtures import TEST_HEADERS, TEST_ORIGIN
from control_plane.limits_fixtures import (
    account_bot,
    claim_run,
    process_queue_attempt,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services


def test_atomic_queue_and_active_capacity_across_connections(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            accounts = [
                await account_bot(sessions)
                for _ in range(PAPER_BETA.global_queued_runs)
            ]
            results = await asyncio.gather(
                *(queue_run(sessions, bot) for _, bot in accounts for _ in range(5)),
                return_exceptions=True,
            )
            runs = [result for result in results if not isinstance(result, Exception)]
            errors = [
                result for result in results if isinstance(result, ResourceLimitError)
            ]
            assert len(runs) == PAPER_BETA.global_queued_runs
            assert len(runs) + len(errors) == len(results)
            async with sessions() as session:
                for user, _ in accounts:
                    assert (
                        await AccountUsageReader(session, user.id).usage()
                    ).queued_runs <= PAPER_BETA.queued_runs
            for _ in range(PAPER_BETA.global_active_runs + 2):
                await asyncio.gather(*(claim_run(sessions, run) for run in runs))
            async with sessions() as session:
                usages = [
                    await AccountUsageReader(session, user.id).usage()
                    for user, _ in accounts
                ]
                assert (
                    sum(usage.active_runs for usage in usages)
                    == PAPER_BETA.global_active_runs
                )
                assert all(
                    usage.active_runs <= PAPER_BETA.active_runs for usage in usages
                )

    asyncio.run(scenario())


def test_fifo_skips_busy_account_and_terminal_release_is_idempotent(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user_a, bot_a = await account_bot(sessions)
            user_b, bot_b = await account_bot(sessions)
            first = await queue_run(sessions, bot_a)
            assert await claim_run(sessions, first)
            waiting = await queue_run(sessions, bot_a)
            eligible = await queue_run(sessions, bot_b)
            async with sessions() as session:
                assert (
                    await RunAdmission(session).next_eligible_queued_run_id()
                    == eligible.id
                )
            assert await claim_run(sessions, eligible)

            async def stop():
                async with sessions() as session:
                    return await ApiRunLifecycle(session).request_stop(
                        waiting.id, now=system_now_utc()
                    )

            outcomes = await asyncio.gather(*(stop() for _ in range(8)))
            assert sum(event_id is not None for _, event_id in outcomes) == 1
            async with sessions() as session:
                store = RunStore(session)
                assert await store.mark_running(first.id)
                assert await store.begin_stopping(first.id)
                assert await store.finish(
                    first.id, status=RunStatus.STOPPED, now=system_now_utc()
                )
                assert not await store.finish(
                    first.id, status=RunStatus.STOPPED, now=system_now_utc()
                )
                usage = await AccountUsageReader(session, user_a.id).usage()
                assert usage.active_runs == usage.queued_runs == 0
            after = await queue_run(sessions, bot_a)
            assert await claim_run(sessions, after)

    asyncio.run(scenario())


def test_launch_failure_and_duration_expiry_release_capacity(
    limits_services, monkeypatch
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            failed = await queue_run(sessions, bot)
            async with sessions() as session:
                await ApiRunLifecycle(session).fail_launch(
                    failed.id,
                    now=system_now_utc(),
                    failure_detail="fixture delivery failure",
                )
            expiring = await queue_run(sessions, bot)

            async def runtime(*args):
                await asyncio.Event().wait()

            monkeypatch.setattr(lifecycle, "run_claimed_bot", runtime)
            monkeypatch.setattr(
                lifecycle,
                "PAPER_BETA",
                PAPER_BETA.model_copy(update={"run_duration_seconds": 0.05}),
            )
            async with sessions() as session:
                await asyncio.wait_for(
                    RunLifecycleCoordinator(
                        RunStore(session), sessions, RunEventWriter(sessions, redis)
                    ).execute(expiring.id),
                    timeout=2,
                )
            async with sessions() as session:
                run = await RunStore(session).read(expiring.id)
                assert run.status is RunStatus.STOPPED
                assert run.failure_detail == DURATION_EXPIRED_DETAIL
                usage = await AccountUsageReader(session, user.id).usage()
                assert usage.active_runs == usage.queued_runs == 0

    asyncio.run(scenario())


def test_saved_resources_and_revisions_are_bounded(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)

            async def create():
                async with sessions() as session:
                    return await BotStore(session, user.id).create(
                        definition_id=bot.definition_id,
                        config=bot.config,
                        graph=STARTER_NODE_GRAPH,
                    )

            results = await asyncio.gather(
                *(create() for _ in range(PAPER_BETA.saved_bots + 5)),
                return_exceptions=True,
            )
            assert (
                sum(not isinstance(result, Exception) for result in results)
                == PAPER_BETA.saved_bots - 1
            )

            async def template(index):
                async with sessions() as session:
                    return await GraphTemplateStore(session, user.id).create(
                        GraphTemplateCreate(
                            name=f"template-{index}", graph=STARTER_NODE_GRAPH
                        )
                    )

            results = await asyncio.gather(
                *(template(index) for index in range(PAPER_BETA.saved_templates + 5)),
                return_exceptions=True,
            )
            assert (
                sum(not isinstance(result, Exception) for result in results)
                == PAPER_BETA.saved_templates
            )
            for _ in range(PAPER_BETA.revisions_per_bot):
                async with sessions() as session:
                    await BotStore(session, user.id).append_revision(
                        bot.id, STARTER_NODE_GRAPH
                    )
            async with sessions() as session:
                with pytest.raises(ResourceLimitError):
                    await BotStore(session, user.id).append_revision(
                        bot.id, STARTER_NODE_GRAPH
                    )

    asyncio.run(scenario())


def test_shared_requests_and_streams_fail_closed_and_release(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            owner = uuid4()
            limits = RequestRateLimiter(redis, owner)
            for _ in range(PAPER_BETA.expensive_requests_per_minute):
                await limits.consume_request_budget(expensive=True)
            with pytest.raises(ResourceLimitError) as error:
                await limits.consume_request_budget(expensive=True)
            assert error.value.code is ResourceLimitCode.USER_ALLOWANCE
            leases = await asyncio.gather(
                *(
                    OpenStreamAdmission(redis, owner).acquire_stream()
                    for _ in range(PAPER_BETA.open_streams)
                )
            )
            with pytest.raises(ResourceLimitError):
                await OpenStreamAdmission(redis, owner).acquire_stream()
            await leases.pop().release()
            leases.append(await OpenStreamAdmission(redis, owner).acquire_stream())
            for _ in range(PAPER_BETA.global_open_streams - len(leases)):
                leases.append(
                    await OpenStreamAdmission(redis, uuid4()).acquire_stream()
                )
            with pytest.raises(ResourceLimitError) as error:
                await OpenStreamAdmission(redis, uuid4()).acquire_stream()
            assert error.value.code is ResourceLimitCode.GLOBAL_CAPACITY
            await asyncio.gather(*(lease.release() for lease in leases))
            await asyncio.gather(*(lease.release() for lease in leases))
            await (await OpenStreamAdmission(redis, owner).acquire_stream()).release()
            broken = AsyncMock()
            broken.eval.side_effect = RedisConnectionError("offline")
            with pytest.raises(RedisConnectionError):
                await RequestRateLimiter(broken, owner).consume_request_budget(
                    expensive=True
                )

    asyncio.run(scenario())


def test_usage_ownership_and_http_capacity_feedback(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            other, other_bot = await account_bot(sessions)
            await queue_run(sessions, other_bot)
            launcher = AsyncMock()

            def app_for(account):
                app = create_app(
                    auth_settings=AuthSettings(TEST_ORIGIN, allow_http=True),
                    session_factory=sessions,
                    redis=redis,
                    launcher=launcher,
                )

                async def identity(request: Request):
                    request.state.user = CurrentUser(id=account.id, email=account.email)

                app.dependency_overrides[application_authentication] = identity
                return app

            apps = [app_for(user), app_for(user)]
            async with (
                AsyncClient(
                    transport=ASGITransport(app=apps[0]),
                    base_url=TEST_ORIGIN,
                    headers=TEST_HEADERS,
                ) as first,
                AsyncClient(
                    transport=ASGITransport(app=apps[1]),
                    base_url=TEST_ORIGIN,
                    headers=TEST_HEADERS,
                ) as second,
            ):
                missing = await first.post(
                    api_route_path(BOT_RUNS_PATH, bot_id=other_bot.id)
                )
                assert missing.status_code == status.HTTP_404_NOT_FOUND
                results = await asyncio.gather(
                    *(
                        client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot.id))
                        for client in [first, second] * 3
                    )
                )
                assert (
                    sum(
                        result.status_code == status.HTTP_202_ACCEPTED
                        for result in results
                    )
                    == PAPER_BETA.queued_runs
                )
                errors = [
                    result
                    for result in results
                    if result.status_code != status.HTTP_202_ACCEPTED
                ]
                assert all(
                    result.status_code == status.HTTP_429_TOO_MANY_REQUESTS
                    and result.json()["code"] == ResourceLimitCode.USER_ALLOWANCE
                    for result in errors
                )
                usage = (await first.get(api_route_path(USAGE_PATH))).json()
                assert usage["queued_runs"] == PAPER_BETA.queued_runs
                assert usage["saved_bots"] == 1
                assert "global_usage" not in usage

    asyncio.run(scenario())


def test_subscription_configuration_and_dynamic_registry_caps():
    market = Market(
        slug="market",
        condition_id="condition",
        outcomes=(MarketOutcome("Up", "up"), MarketOutcome("Down", "down")),
        question="Fixture",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal(0),
    )
    config = CATALOG[WINNER_DEFINITION_ID].parse_config({"name": "limits"})
    config = config.model_copy(
        update={
            "stream_rules": (
                StreamRule(
                    StreamRelation.INDEPENDENT,
                    tuple(
                        f"market-{index}"
                        for index in range(PAPER_BETA.tracked_markets_per_run + 1)
                    ),
                ),
            )
        }
    )
    with pytest.raises(ResourceLimitError) as error:
        config.require_subscription_allowance()
    assert error.value.code is ResourceLimitCode.INVALID_CONFIGURATION
    registry = TrackedMarketRegistry(
        max_tracked_markets=PAPER_BETA.tracked_markets_per_run
    )
    markets = [
        replace(market, condition_id=f"condition-{index}", slug=f"market-{index}")
        for index in range(PAPER_BETA.tracked_markets_per_run + 1)
    ]
    for item in markets[:-1]:
        registry.add(item, MarketInterest.CONFIGURED)
    assert not registry.add(markets[0], MarketInterest.CONFIGURED)
    with pytest.raises(TrackedMarketLimitExceeded):
        registry.add(markets[-1], MarketInterest.FOLLOWED_WALLET)
    assert len(registry.markets) == PAPER_BETA.tracked_markets_per_run
    registry.resolve(markets[0].condition_id)
    assert registry.add(markets[-1], MarketInterest.BROKER_POSITION)


def test_separate_api_processes_share_queue_reservations(limits_services):
    async def setup():
        async with resource_services(limits_services) as (sessions, redis):
            return await account_bot(sessions)

    _, bot = asyncio.run(setup())
    with ProcessPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(process_queue_attempt, [limits_services[0]] * 12, [bot] * 12)
        )
    assert sum(results) == PAPER_BETA.queued_runs
