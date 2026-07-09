from __future__ import annotations

import asyncio
from collections.abc import Sequence

from app.config import AppConfig
from app.db import create_database_engine, create_session_factory
from app.redis import create_redis_client
from app.services.follows.registry import rebuild_active_follow_registry
from app.services.follows.restart import apply_restart_rearm
from app.services.mirroring.events import MirrorEventProcessor
from app.services.polymarket.clob_client import ClobClient
from app.services.polymarket.data_client import DataClient
from app.services.ws.debounce.attribution import AttributionDebouncer
from app.services.ws.market_watcher import (
    MarketWatcher,
    exponential_backoff_ladder,
)
from app.services.ws.subscription_sync import (
    DEFAULT_WATCHED_TOKEN_SYNC_SECONDS,
    run_watcher_subscription_sync_loop,
)
from app.services.ws.subscription_registry import WatchedTokenRegistry
from app.services.ws.watcher_health import (
    WATCHER_HEALTH_INTERVAL_SECONDS,
    write_watcher_health,
)


def log_worker_status(message: str) -> None:
    print(f"[mirror-worker] {message}", flush=True)


async def run_worker(config: AppConfig) -> None:
    log_worker_status("starting")

    engine = create_database_engine(config)
    session_factory = create_session_factory(engine)
    redis = create_redis_client(config)
    registry = WatchedTokenRegistry(redis)

    try:
        async with session_factory() as session:
            # Crash recovery (spec 6.6): never auto-resume execution after a
            # restart. Re-armed follows stay observed but require an explicit
            # re-arm before mirroring again.
            rearmed_follow_ids = await apply_restart_rearm(
                session,
                rearm_on_restart=config.rearm_on_restart,
            )
            token_ids = await rebuild_active_follow_registry(session, registry)

        log_worker_status(
            f"restart re-arm ({config.rearm_on_restart.value}): "
            f"{len(rearmed_follow_ids)} follow(s) -> needs_rearm"
        )
        log_worker_status(
            f"registry rebuilt; watching {len(token_ids)} token(s)"
        )

        async with (
            DataClient(
                base_url=config.polymarket.data_api_base_url,
                timeout=config.attribution.timeout_ms / 1000,
            ) as data_client,
            ClobClient(base_url=config.polymarket.clob_api_base_url) as clob_client,
        ):
            processor = MirrorEventProcessor(
                session_factory=session_factory,
                registry=registry,
                data_client=data_client,
                clob_client=clob_client,
                paper_config=config.paper,
                redis=redis,
                debouncer=AttributionDebouncer(
                    window_seconds=config.attribution.debounce_ms / 1000,
                ),
                trades_budget_per_10s=config.attribution.trades_budget_per_10s,
            )
            watcher = MarketWatcher(
                url=config.polymarket.market_ws_url,
                token_ids=token_ids,
                ping_interval_seconds=config.market_ws.ping_interval_seconds,
                reconnect_backoff_seconds=exponential_backoff_ladder(
                    config.market_ws.reconnect_backoff_max_seconds,
                ),
                event_handler=processor.handle_event,
            )
            log_worker_status(
                "running; "
                f"market_ws={config.polymarket.market_ws_url}; "
                f"subscription_sync={DEFAULT_WATCHED_TOKEN_SYNC_SECONDS:.1f}s"
            )
            async with asyncio.TaskGroup() as task_group:
                task_group.create_task(watcher.run_forever())
                task_group.create_task(run_trailing_checks(processor, config))
                task_group.create_task(
                    run_watcher_subscription_sync_loop(
                        registry=registry,
                        watcher=watcher,
                    )
                )
                task_group.create_task(
                    run_watcher_health_loop(watcher, redis)
                )
    finally:
        close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
        if callable(close):
            result = close()
            if asyncio.iscoroutine(result):
                await result
        await engine.dispose()
        log_worker_status("stopped")


async def run_trailing_checks(
    processor: MirrorEventProcessor,
    config: AppConfig,
) -> None:
    interval_seconds = max(config.attribution.debounce_ms / 1000, 0.05)
    while True:
        await asyncio.sleep(interval_seconds)
        await processor.process_due_trailing_checks()


async def run_watcher_health_loop(watcher: MarketWatcher, redis) -> None:
    while True:
        await write_watcher_health(
            redis,
            ws_connected=watcher.connected,
            watched_token_count=len(watcher.subscribed_token_ids),
        )
        await asyncio.sleep(WATCHER_HEALTH_INTERVAL_SECONDS)


def main(argv: Sequence[str] | None = None) -> None:
    del argv
    asyncio.run(run_worker(AppConfig.from_env()))


if __name__ == "__main__":
    main()
