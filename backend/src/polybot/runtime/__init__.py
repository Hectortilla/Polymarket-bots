"""Public paper-runner lifecycle orchestration."""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import replace
from pathlib import Path
from time import monotonic

from polybot.cli.observability.events import (
    RuntimeFailed,
    RuntimeStarted,
    RuntimeState,
    RuntimeStateChanged,
)
from polybot.cli.observability.observer import (
    NullRuntimeObserver,
    RuntimeObserver,
    RuntimeObserverGroup,
    emit_observer_fail_open,
    start_observer_fail_open,
    stop_observer_fail_open,
)
from polybot.framework.base import BaseBot
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.framework.runner import BotRunner
from polybot.polymarket.public_data.runtime import RuntimePublicData
from polybot.polymarket.wallet_activity.contracts import WalletTradeSource
from polybot.performance.artifacts.errors import PerformanceOutputExistsError
from polybot.performance.contracts.sampling import DEFAULT_REPORT_INTERVAL_MS
from polybot.cli.runner.factory import create_runtime

from .performance.broker import PaperPerformanceBroker
from .performance.observer import PaperPerformanceObserver
from .performance.recording import PaperPerformanceRecorder
from .performance.setup import create_paper_performance_recorder
from .performance.warnings import PaperPerformanceWarning
from .streams import run_runtime_streams


async def run_bot(
    bot: BaseBot,
    config: BotConfig,
    *,
    wallet_source: WalletTradeSource | None = None,
    public_data: RuntimePublicData | None = None,
    observer: RuntimeObserver | None = None,
    results_dir: str | Path | None = None,
    bot_spec: str | None = None,
    report_interval_ms: int = DEFAULT_REPORT_INTERVAL_MS,
) -> None:
    """Run one bot using public market data and the paper broker."""
    if config.mode is BotMode.LIVE:
        raise RuntimeError("live mode is not available in the paper runner CLI")
    primary_observer = observer or NullRuntimeObserver()
    observer_group = RuntimeObserverGroup(primary_observer)
    runtime_observer: RuntimeObserver = (
        observer_group if results_dir is not None else primary_observer
    )
    runtime = await create_runtime(
        config,
        runtime_observer,
        public_data=public_data,
    )
    paper_broker = runtime.paper_broker
    ctx = runtime.ctx
    performance_recorder: PaperPerformanceRecorder | None = None
    if results_dir is not None:
        try:
            performance_recorder = await create_paper_performance_recorder(
                results_dir,
                bot_spec=bot_spec or config.name,
                config=config,
                ctx=ctx,
                portfolio=paper_broker.portfolio,
                report_interval_ms=report_interval_ms,
            )
        except PerformanceOutputExistsError:
            await runtime.public_data.close()
            raise
        except Exception as error:
            warnings.warn(
                "paper performance recording could not start: "
                f"{type(error).__name__}: {error}",
                PaperPerformanceWarning,
                stacklevel=2,
            )
        else:
            observer_group.add(PaperPerformanceObserver(performance_recorder))
            ctx = replace(
                ctx,
                broker=PaperPerformanceBroker(
                    runtime.broker,
                    recorder=performance_recorder,
                    clock=ctx.clock,
                ),
            )
    runner = BotRunner(bot, ctx)
    await start_observer_fail_open(runtime_observer, config)
    emit_observer_fail_open(runtime_observer, RuntimeStarted.from_config(config))
    emit_observer_fail_open(
        runtime_observer,
        RuntimeStateChanged(RuntimeState.STARTING, monotonic()),
    )
    failed = False
    try:
        await bot.on_start(ctx)
        emit_observer_fail_open(
            runtime_observer,
            RuntimeStateChanged(RuntimeState.RUNNING, monotonic()),
        )
        await run_runtime_streams(
            runner,
            config,
            runtime,
            wallet_source=wallet_source,
            observer=runtime_observer,
        )
    except asyncio.CancelledError:
        if performance_recorder is not None:
            performance_recorder.mark_cancelled()
        raise
    except BaseException as error:
        if not isinstance(error, asyncio.CancelledError):
            failed = True
            emit_observer_fail_open(
                runtime_observer,
                RuntimeFailed(f"{type(error).__name__}: {error}", monotonic()),
            )
        raise
    finally:
        if not failed:
            emit_observer_fail_open(
                runtime_observer,
                RuntimeStateChanged(RuntimeState.STOPPING, monotonic()),
            )
        try:
            try:
                await bot.on_stop(ctx)
            finally:
                await runtime.public_data.close()
        except BaseException as error:
            failed = True
            if not isinstance(error, asyncio.CancelledError):
                emit_observer_fail_open(
                    runtime_observer,
                    RuntimeFailed(f"{type(error).__name__}: {error}", monotonic()),
                )
            raise
        finally:
            if not failed:
                emit_observer_fail_open(
                    runtime_observer,
                    RuntimeStateChanged(RuntimeState.STOPPED, monotonic()),
                )
            await stop_observer_fail_open(runtime_observer)
