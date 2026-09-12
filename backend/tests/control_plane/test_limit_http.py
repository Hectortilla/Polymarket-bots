"""HTTP admission failures preserve typed status, retry and ownership contracts."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import api.limits.redis.request_budgets as budgets
import pytest
from api.bots.models import BotRow
from api.catalog.inputs import WalletPaperLaunchInputs
from api.http.protocol import RETRY_AFTER_HEADER
from api.http.routes.paths import (
    BOT_RUNS_PATH,
    MARKET_SEARCH_PATH,
    USAGE_PATH,
    WALLET_LOOKUP_PATH,
    WALLET_SEARCH_PATH,
    api_route_path,
)
from api.limits.errors import ResourceLimitCode
from api.limits.policy import PAPER_BETA
from api.limits.redis.contracts import ResourceAdmissionOutcome
from api.limits.redis.request_budgets import RequestRateLimiter
from api.runs.store import RunStore
from fastapi import status
from httpx import ASGITransport, AsyncClient
from polybot.framework.clock import system_now_utc
from polybot.framework.streams import StreamRelation, StreamRule
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from control_plane.auth_fixtures import TEST_HEADERS, TEST_ORIGIN
from control_plane.limits_fixtures import (
    account_app,
    account_bot,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services


@pytest.mark.parametrize("value", [False, True, 0.0, "0", None, -1, 3])
def test_malformed_redis_outcome_fails_closed(value):
    with pytest.raises(RuntimeError):
        ResourceAdmissionOutcome.from_redis(value)


@pytest.mark.parametrize(
    "expensive,global_capacity", [(False, False), (False, True), (True, True)]
)
def test_http_shared_request_limits(
    limits_services, monkeypatch, expensive, global_capacity
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            policy = PAPER_BETA.model_copy(
                update={
                    "requests_per_minute": 6,
                    "global_requests_per_minute": 10,
                    "expensive_requests_per_minute": 2,
                    "global_expensive_requests_per_minute": 3,
                }
            )
            monkeypatch.setattr(budgets, "PAPER_BETA", policy)
            user, bot = await account_bot(sessions)
            total = (
                (
                    policy.global_expensive_requests_per_minute
                    if expensive
                    else policy.global_requests_per_minute
                )
                if global_capacity
                else policy.requests_per_minute
            )
            for _ in range(total):
                owner = uuid4() if global_capacity else user.id
                await RequestRateLimiter(redis, owner).consume_request_budget(
                    expensive=expensive
                )
            app = account_app(sessions, redis, user)
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url=TEST_ORIGIN,
                headers=TEST_HEADERS,
            ) as client:
                response = (
                    await client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot.id))
                    if expensive
                    else await client.get(api_route_path(USAGE_PATH))
                )
            expected_code = (
                ResourceLimitCode.GLOBAL_CAPACITY
                if global_capacity
                else ResourceLimitCode.USER_ALLOWANCE
            )
            assert response.status_code == (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if global_capacity
                else status.HTTP_429_TOO_MANY_REQUESTS
            )
            assert response.json()["code"] == expected_code
            assert int(response.headers[RETRY_AFTER_HEADER]) > 0

    asyncio.run(scenario())


def test_http_global_queue_and_invalid_persisted_subscriptions(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            for _ in range(PAPER_BETA.global_queued_runs):
                _, queued_bot = await account_bot(sessions)
                await queue_run(sessions, queued_bot)
            user, bot = await account_bot(sessions)
            app = account_app(sessions, redis, user)
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url=TEST_ORIGIN,
                headers=TEST_HEADERS,
            ) as client:
                path = api_route_path(BOT_RUNS_PATH, bot_id=bot.id)
                busy = await client.post(path)
                assert busy.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
                assert busy.json()["code"] == ResourceLimitCode.GLOBAL_CAPACITY
                assert RETRY_AFTER_HEADER in busy.headers
                async with sessions() as session:
                    row = await session.get(BotRow, bot.id)
                    row.config = bot.config.model_copy(
                        update={
                            "stream_rules": (
                                StreamRule(
                                    StreamRelation.INDEPENDENT,
                                    wallet_addresses=tuple(
                                        f"0x{i:040x}"
                                        for i in range(
                                            PAPER_BETA.followed_wallets_per_run + 1
                                        )
                                    ),
                                ),
                            )
                        }
                    ).model_dump(mode="json")
                    await session.commit()
                invalid = await client.post(path)
                assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
                assert invalid.json()["code"] == ResourceLimitCode.INVALID_CONFIGURATION
                assert RETRY_AFTER_HEADER not in invalid.headers
                malformed_id = await client.post(
                    api_route_path(BOT_RUNS_PATH, bot_id="invalid")
                )
                assert malformed_id.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
                assert isinstance(malformed_id.json()["detail"], list)

    asyncio.run(scenario())


def test_http_missing_redis_fails_closed(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, _ = await account_bot(sessions)
            broken = AsyncMock()
            broken.eval.side_effect = RedisConnectionError("offline")
            app = account_app(sessions, broken, user)
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url=TEST_ORIGIN,
            ) as client:
                response = await client.get(api_route_path(USAGE_PATH))
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    asyncio.run(scenario())


def test_wallet_allowance_rejected_at_launch_input_ingress():
    with pytest.raises(ValidationError):
        WalletPaperLaunchInputs(
            name="too many wallets",
            wallet_addresses=tuple(
                f"0x{i:040x}" for i in range(PAPER_BETA.followed_wallets_per_run + 1)
            ),
        )


def test_usage_counts_only_owned_terminal_runs(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            _, foreign = await account_bot(sessions)
            for selected in (bot, foreign, foreign):
                run = await queue_run(sessions, selected)
                async with sessions() as session:
                    await RunStore(session).request_stop(run.id, now=system_now_utc())
            async with AsyncClient(
                transport=ASGITransport(app=account_app(sessions, redis, user)),
                base_url=TEST_ORIGIN,
            ) as client:
                usage = (await client.get(api_route_path(USAGE_PATH))).json()
            assert usage["retained_runs"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "path,method",
    [
        (MARKET_SEARCH_PATH, "GET"),
        (WALLET_SEARCH_PATH, "GET"),
        (WALLET_LOOKUP_PATH, "POST"),
    ],
)
def test_discovery_consumes_expensive_budget_before_upstream(
    limits_services, path, method
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, _ = await account_bot(sessions)
            for _ in range(PAPER_BETA.expensive_requests_per_minute):
                await RequestRateLimiter(redis, user.id).consume_request_budget(
                    expensive=True
                )
            app = account_app(sessions, redis, user)
            discovery = AsyncMock()
            app.state.market_discovery = discovery
            app.state.wallet_discovery = discovery
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url=TEST_ORIGIN,
                headers=TEST_HEADERS,
            ) as client:
                response = await client.request(
                    method,
                    api_route_path(path),
                    **(
                        {"params": {"q": "market"}}
                        if method == "GET"
                        else {"json": {"addresses": ["0x" + "ab" * 20]}}
                    ),
                )
            assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
            assert response.json()["code"] == ResourceLimitCode.USER_ALLOWANCE
            assert not discovery.mock_calls

    asyncio.run(scenario())
