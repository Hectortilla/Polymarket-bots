"""Deterministic market/runtime inputs in an isolated acceptance image only."""

import argparse
import asyncio
import os

import api.execution.worker.lifecycle as lifecycle
import uvicorn
from api.deployment.schema import DeploymentSchema
from api.deployment.services import DeploymentService
from api.deployment.settings import API_PORT, API_WORKERS, StartupSettings
from api.events.contracts import RunLifecycleEvent
from api.events.contracts.payloads.lifecycle import RunStatusPayload
from api.events.writer import RunEventWriter
from api.execution.policy import TASKIQ_DRAIN_SECONDS, TASKIQ_SHUTDOWN_SECONDS
from api.execution.recovery.__main__ import serve_recovery
from api.execution.taskiq_app import broker  # noqa: F401
from api.http.app import create_app as application
from api.runs.status import RunStatus
from polybot.framework.clock import system_now_utc
from polybot.polymarket.discovery_contracts import MarketSearchResults
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from control_plane.market_fixtures import market_discovery, market_suggestion


async def fixture_runtime(run, observer, **kwargs):
    settings = await asyncio.to_thread(StartupSettings.from_env)
    engine = create_async_engine(
        settings.database_url.get_secret_value(), hide_parameters=True
    )
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        writer = RunEventWriter(
            async_sessionmaker(engine, expire_on_commit=False),
            redis,
            execution_token=run.execution_token,
            lease_seconds=settings.lease_seconds,
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "service",
        type=DeploymentService,
        choices=(
            DeploymentService.API,
            DeploymentService.WORKER,
            DeploymentService.RECOVERY,
        ),
    )
    args = parser.parse_args()
    settings = StartupSettings.from_env()
    asyncio.run(DeploymentSchema(settings).require_compatible())
    if args.service is DeploymentService.API:
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
    elif args.service is DeploymentService.WORKER:
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
                "--wait-tasks-timeout",
                str(TASKIQ_DRAIN_SECONDS),
                "--shutdown-timeout",
                str(TASKIQ_SHUTDOWN_SECONDS),
            ],
        )
    else:
        asyncio.run(serve_recovery(settings))


if __name__ == "__main__":
    main()
