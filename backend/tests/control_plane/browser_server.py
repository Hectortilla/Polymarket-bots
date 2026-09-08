"""Disposable browser acceptance server with real identity, persistence and Redis.

Only market discovery and queued execution delivery are fixtures. No Polymarket
network call or trading side effect is needed to verify browser ownership.
"""

import argparse
import asyncio
import os

import uvicorn
from api.auth.config import AuthSettings
from api.database import DATABASE_URL_ENV
from api.http.app import create_app
from polybot.polymarket.discovery_contracts import MarketSearchResults
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from control_plane.disposable_services import (
    clear_auth_attempts,
    disposable_postgres_url,
    disposable_redis_url,
)
from control_plane.market_fixtures import market_discovery, market_suggestion
from scripts.recreate_control_plane_database import main as recreate_database


class BrowserRunQueue:
    def __init__(self, redis):
        self.redis = redis

    async def launch(self, run_id):
        await self.redis.rpush("polybot:browser:queued-runs", str(run_id))


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
        markets=(market_suggestion("browser-market"),), has_more=False
    )
    app = create_app(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        redis=redis,
        launcher=BrowserRunQueue(redis),
        market_discovery=discovery,
        auth_settings=AuthSettings(args.origin, True),
    )
    uvicorn.run(app, host=args.api_host, port=args.api_port, proxy_headers=False)


if __name__ == "__main__":
    main()
