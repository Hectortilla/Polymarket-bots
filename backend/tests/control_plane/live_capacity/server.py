"""Real HTTP server with explicit fixture-only admission overrides."""

import asyncio
from time import monotonic
from unittest.mock import AsyncMock
from uuid import UUID

import uvicorn
from api.auth.config import AuthSettings
from api.auth.dependencies import CurrentUserDependency
from api.events.live.connections import LiveConnections
from api.execution.worker.database import create_worker_database
from api.http.app import create_app
from api.http.dependencies import SessionFactoryDependency
from api.http.routes.run_lookup import require_stored_run
from api.http.sse.hub import LiveSubscriptionHub
from api.io_policy import REDIS_CONTROL_POOL_SIZE, REDIS_SOCKET_OPTIONS
from api.limits.http import application_resource_limits, stream_lease
from api.limits.redis.stream_admission import StreamLease
from redis.asyncio import Redis

from control_plane.live_capacity.measurements import Measurements


def run_server(settings, sock, stop, report, duration):
    asyncio.run(serve(settings, sock, stop, report, duration))


async def serve(settings, sock, stop, report, duration):
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    engine, sessions = create_worker_database(settings.database_url.get_secret_value())
    redis = Redis.from_url(
        settings.redis_url.get_secret_value(),
        max_connections=REDIS_CONTROL_POOL_SIZE,
        **REDIS_SOCKET_OPTIONS,
    )
    live = LiveConnections(settings)
    measurements = Measurements()
    measurements.instrument_sql(engine)
    hub = LiveSubscriptionHub(live.router, live.clients, redis)
    app = create_app(
        auth_settings=AuthSettings(origin, True),
        session_factory=sessions,
        redis=redis,
        launcher=AsyncMock(),
        market_discovery=AsyncMock(),
        wallet_discovery=AsyncMock(),
    )
    app.state.live_subscription_hub = hub
    # Capacity fixtures replace only request/stream count quotas. Identity, owner
    # lookups, cached session rechecks, replay and SSE transport remain production.
    app.dependency_overrides[application_resource_limits] = lambda: None

    async def capacity_lease(
        run_id: UUID,
        session_factory: SessionFactoryDependency,
        user: CurrentUserDependency,
    ):
        async with session_factory() as session:
            await require_stored_run(session, run_id, user.id)
        yield StreamLease(
            redis, ("fixture", "fixture"), "fixture", monotonic() + duration + 60
        )

    app.dependency_overrides[stream_lease] = capacity_lease
    await hub.start()
    server = uvicorn.Server(
        uvicorn.Config(
            app, log_level="error", access_log=False, timeout_graceful_shutdown=2
        )
    )

    async def monitor():
        while not stop.is_set():
            before = monotonic()
            measurements.observe(
                "subscription_connections",
                hub.metrics.snapshot().get("subscription_connections", 0),
            )
            if (
                hub.metrics.snapshot().get("subscription_connections", 0)
                > len(live.clients) + 1
            ):
                measurements.add("subscription_bound_violations")
            await measurements.write(
                report,
                hub.metrics.snapshot(),
                viewers=sum(map(len, hub._viewers.values())),
            )
            await asyncio.sleep(1)
            measurements.observe("loop_lag_seconds", max(0, monotonic() - before - 1))
        server.should_exit = True

    task = asyncio.create_task(monitor())
    try:
        await server.serve(sockets=[sock])
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await hub.close()
        await measurements.write(report, hub.metrics.snapshot(), clean_shutdown=True)
        await live.close()
        await redis.aclose()
        await engine.dispose()
