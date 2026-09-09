"""Deterministic market/runtime inputs in an isolated acceptance image only."""

import argparse
import asyncio
import os
from datetime import timedelta
from uuid import UUID

import uvicorn
from polybot.framework.clock import system_now_utc
from polybot.polymarket.discovery_contracts import MarketSearchResults
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.execution.worker.lifecycle as lifecycle
from api.deployment.schema import DeploymentSchema
from api.deployment.settings import API_PORT, API_WORKERS, StartupSettings
from api.events.contracts import RunLifecycleEvent
from api.events.contracts.payloads.lifecycle import RunStatusPayload
from api.events.writer import RunEventWriter
from api.execution.taskiq_app import broker  # noqa: F401
from api.execution.worker.lease import reconcile_expired_run
from api.http.app import create_app as application
from api.runs.status import RunStatus
from control_plane.market_fixtures import market_discovery, market_suggestion


async def fixture_runtime(run, observer):
    settings = await asyncio.to_thread(StartupSettings.from_env)
    engine = create_async_engine(
        settings.database_url.get_secret_value(), hide_parameters=True
    )
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        writer = RunEventWriter(
            async_sessionmaker(engine, expire_on_commit=False), redis
        )
        await writer.append(
            RunLifecycleEvent(
                run_id=run.id,
                occurred_at=system_now_utc(),
                payload=RunStatusPayload(status=RunStatus.RUNNING),
            )
        )
        await asyncio.Event().wait()
    finally:
        await redis.aclose()
        await engine.dispose()


# Taskiq imports this module in each worker process. Only the external runtime
# is replaced; delivery, claims, heartbeat, Stop and terminal writes stay real.
lifecycle.run_claimed_bot = fixture_runtime


def create_app():
    discovery = market_discovery()
    discovery.search.return_value = MarketSearchResults(
        markets=(market_suggestion("browser-market"),),
        has_more=False,
    )
    return application(market_discovery=discovery)


async def reconcile(run_id: UUID):
    settings = await asyncio.to_thread(StartupSettings.from_env)
    engine = create_async_engine(
        settings.database_url.get_secret_value(), hide_parameters=True
    )
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        now = system_now_utc()
        await reconcile_expired_run(
            run_id,
            now=now,
            expired_before=now - timedelta(seconds=settings.lease_seconds),
            session_factory=sessions,
            event_writer=RunEventWriter(sessions, redis),
        )
    finally:
        await redis.aclose()
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=("api", "worker", "reconcile"))
    parser.add_argument("run_id", nargs="?", type=UUID)
    args = parser.parse_args()
    settings = StartupSettings.from_env()
    asyncio.run(DeploymentSchema(settings).require_compatible())
    if args.service == "api":
        uvicorn.run(
            "control_plane.deployment_fixture:create_app",
            factory=True,
            host="0.0.0.0",
            port=API_PORT,
            workers=API_WORKERS,
            proxy_headers=True,
            forwarded_allow_ips=settings.proxy_address,
            access_log=False,
        )
    elif args.service == "worker":
        os.execvp(
            "taskiq",
            [
                "taskiq",
                "worker",
                "control_plane.deployment_fixture:broker",
                "--workers",
                "1",
                "--max-async-tasks",
                str(settings.worker_concurrency),
            ],
        )
    else:
        asyncio.run(reconcile(args.run_id))


if __name__ == "__main__":
    main()
