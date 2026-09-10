"""Disposable identity/persistence/browser server with normalized market fixtures.

Onboarding cases run the real graph, paper broker and lease coordinator without
external market transport; legacy ownership scenarios inspect queued delivery.
"""

import argparse
import asyncio
import os

import uvicorn
from api.auth.config import AuthSettings
from api.database import DATABASE_URL_ENV
from api.execution.worker import lifecycle
from api.http.app import create_app
from polybot.polymarket.discovery_contracts import MarketSearchResults
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from control_plane.account_mail_fixture import install_browser_mailbox
from control_plane.browser_launcher import BrowserRunLauncher
from control_plane.browser_limits_fixture import install_browser_limit_control
from control_plane.disposable_services import (
    clear_auth_attempts,
    disposable_postgres_url,
    disposable_redis_url,
)
from control_plane.market_fixtures import market_discovery, market_suggestion
from control_plane.onboarding_fixture.runtime import onboarding_runtime
from control_plane.onboarding_policy import ONBOARDING_CASES
from scripts.recreate_control_plane_database import main as recreate_database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--api-host", required=True)
    parser.add_argument("--api-port", required=True, type=int)
    args = parser.parse_args()
    raw_url = os.environ["POLYBOT_BROWSER_POSTGRES_URL"]
    url = disposable_postgres_url(raw_url)
    redis_url = disposable_redis_url(os.environ["POLYBOT_BROWSER_REDIS_URL"])
    os.environ[DATABASE_URL_ENV] = raw_url
    recreate_database()
    redis = Redis.from_url(redis_url)

    async def clear_auth_limits():
        try:
            await clear_auth_attempts(redis)
        finally:
            await redis.aclose()

    asyncio.run(clear_auth_limits())
    redis = Redis.from_url(redis_url)
    engine = create_async_engine(url, hide_parameters=True)
    discovery = market_discovery()
    discovery.search.return_value = MarketSearchResults(
        markets=tuple(
            market_suggestion(slug)
            for slug in (
                "browser-market",
                *(case.market_slug for case in ONBOARDING_CASES.values()),
            )
        ),
        has_more=False,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    # Replace external inputs only; the fixture uses real graph/broker/lease paths.
    lifecycle.run_claimed_bot = onboarding_runtime
    launcher = BrowserRunLauncher(redis, sessions)
    app = create_app(
        session_factory=sessions,
        redis=redis,
        launcher=launcher,
        market_discovery=discovery,
        auth_settings=AuthSettings(args.origin, True),
    )
    launcher.install_lifespan(app)
    install_browser_limit_control(app)
    install_browser_mailbox(app, args.origin)
    uvicorn.run(app, host=args.api_host, port=args.api_port, proxy_headers=False)


if __name__ == "__main__":
    main()
