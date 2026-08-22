"""Lifecycle orchestration for one claimed paper run."""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot.framework.clock import system_now_utc
from polybot_control_plane.events.contracts import RunLifecycleEvent
from polybot_control_plane.events.observer import WebRuntimeObserver
from polybot_control_plane.events.writer import RunEventWriter
from polybot_control_plane.runs.status import RunStatus
from polybot_control_plane.runs.store import RunStore

from .runtime import run_claimed_bot


WORKER_POLL_INTERVAL_SECONDS = 5
PAPER_RUN_FAILURE_REASON = "paper run failed"


async def execute_claimed_run_lifecycle(
    run_id: UUID,
    store: RunStore,
    session_factory: async_sessionmaker[AsyncSession],
    event_writer: RunEventWriter,
) -> None:
    try:
        run = await store.claim(run_id, now=system_now_utc())
    except Exception as error:
        await _finish_run(
            run_id,
            store,
            event_writer,
            RunStatus.FAILED,
            failure_detail=_sanitized_failure_detail(error),
        )
        return
    if run is None:
        return

    terminal_status = RunStatus.STOPPED
    failure_detail: str | None = None
    propagate_cancellation = False
    observer = WebRuntimeObserver(run_id, event_writer)
    try:
        if not await store.mark_running(run_id):
            # A stop can win after the atomic claim but before execution starts;
            # complete that durable request without constructing the bot.
            if await store.status(run_id) is RunStatus.STOP_REQUESTED:
                await store.begin_stopping(run_id)
                await _finish_run(
                    run_id,
                    store,
                    event_writer,
                    RunStatus.STOPPED,
                )
            return
        bot_task = asyncio.create_task(run_claimed_bot(run, observer))
        cooperative_stop = asyncio.Event()
        monitor_task = asyncio.create_task(
            poll_stop_request_and_heartbeat(
                run_id,
                bot_task,
                cooperative_stop,
                session_factory,
            )
        )
        try:
            await bot_task
        except asyncio.CancelledError:
            # Only the durable stop monitor owns a graceful STOPPED cancellation;
            # cancellation from Taskiq/process shutdown records lease interruption.
            if not cooperative_stop.is_set():
                terminal_status = RunStatus.INTERRUPTED
                propagate_cancellation = True
        finally:
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
    except asyncio.CancelledError:
        terminal_status = RunStatus.INTERRUPTED
        propagate_cancellation = True
    except Exception as error:
        terminal_status = RunStatus.FAILED
        failure_detail = _sanitized_failure_detail(error)
    else:
        if terminal_status is RunStatus.STOPPED:
            await store.begin_completion(run_id)

    await _finish_run(
        run_id,
        store,
        event_writer,
        terminal_status,
        failure_detail=failure_detail,
    )
    if propagate_cancellation:
        raise asyncio.CancelledError


async def poll_stop_request_and_heartbeat(
    run_id: UUID,
    bot_task: asyncio.Task[None],
    cooperative_stop: asyncio.Event,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    while not bot_task.done():
        await asyncio.sleep(WORKER_POLL_INTERVAL_SECONDS)
        async with session_factory() as session:
            store = RunStore(session)
            status = await store.status(run_id)
            if status is None:
                return
            if status is RunStatus.STOP_REQUESTED:
                if await store.begin_stopping(run_id):
                    # Mark the durable transition before local cancellation so
                    # another process never has to infer why the bot stopped.
                    cooperative_stop.set()
                    bot_task.cancel()
                return
            await store.heartbeat(run_id, now=system_now_utc())


async def _finish_run(
    run_id: UUID,
    store: RunStore,
    event_writer: RunEventWriter,
    status: RunStatus,
    *,
    failure_detail: str | None = None,
) -> None:
    occurred_at = system_now_utc()
    if not await store.finish(
        run_id,
        status=status,
        now=occurred_at,
        failure_detail=failure_detail,
    ):
        return
    try:
        await event_writer.append(
            RunLifecycleEvent.from_terminal_status(
                run_id,
                status,
                occurred_at=occurred_at,
            )
        )
    except Exception:
        # The run outcome is authoritative even when web observability is down.
        return


def _sanitized_failure_detail(error: Exception) -> str:
    return f"{type(error).__name__}: {PAPER_RUN_FAILURE_REASON}"
