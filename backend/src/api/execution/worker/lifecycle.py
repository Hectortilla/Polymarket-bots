"""Lifecycle orchestration for one claimed paper run."""

import asyncio
from uuid import UUID

from polybot.cli.tracked_markets import TrackedMarketLimitExceeded
from polybot.framework.clock import system_now_utc
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.catalog.definitions import GraphRequirementError
from api.events.observer import WebRuntimeObserver
from api.events.writer import RunEventWriter
from api.execution.policy import RUNTIME_CLEANUP_SECONDS
from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.limits.policy import PAPER_BETA
from api.runs.failures import (
    NEW_RUN_GUIDANCE,
    ExecutionOwnershipLost,
    RunFailureReason,
    RunSnapshotError,
    sanitized_failure_detail,
)
from api.runs.lease import ExecutionLease
from api.runs.lease_policy import DEFAULT_HEARTBEAT_SECONDS, DEFAULT_LEASE_SECONDS
from api.runs.status import RunStatus
from api.runs.store import OwnedRunStore, RunStore

from .fill_ownership import FillOwnership
from .runtime import run_claimed_bot

WORKER_POLL_INTERVAL_SECONDS = DEFAULT_HEARTBEAT_SECONDS
PAPER_RUN_FAILURE_REASON = "paper run failed"
DURATION_EXPIRED_DETAIL = "Paper-run duration allowance reached. " + NEW_RUN_GUIDANCE


class RunLifecycleCoordinator:
    """Own the durable state and event dependencies for one worker lifecycle."""

    def __init__(
        self,
        store: RunStore,
        session_factory: async_sessionmaker[AsyncSession],
        event_writer: RunEventWriter,
        heartbeat_seconds: float = WORKER_POLL_INTERVAL_SECONDS,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self._claim_store = store
        self._execution_store: OwnedRunStore | None = None
        self._session_factory = session_factory
        self._event_writer = event_writer
        self._heartbeat_seconds = heartbeat_seconds
        self._lease_seconds = lease_seconds
        self._lease: ExecutionLease | None = None

    async def execute(self, run_id: UUID) -> None:
        try:
            run = await self._claim_store.claim(run_id, now=system_now_utc())
        except (ValidationError, GraphRequirementError, RunSnapshotError) as error:
            await self._claim_store.fail_queued(
                run_id,
                now=system_now_utc(),
                failure_detail=sanitized_failure_detail(
                    error,
                    PAPER_RUN_FAILURE_REASON,
                ),
            )
            return
        if run is None:
            return

        self._lease = ExecutionLease(run.execution_token, self._lease_seconds)
        self._execution_store = self._claim_store.owned_by(self._lease)
        terminal_status = RunStatus.STOPPED
        failure_detail: str | None = None
        propagate_cancellation = False
        observer = WebRuntimeObserver(
            run_id,
            self._event_writer.for_execution(run.execution_token, self._lease_seconds),
        )
        try:
            if not await self._execution_store.mark_running(run_id):
                # A stop can win after the atomic claim but before execution starts;
                # complete that durable request without constructing the bot.
                if (
                    await self._execution_store.status(run_id)
                    is RunStatus.STOP_REQUESTED
                ):
                    await self._execution_store.begin_stopping(run_id)
                    await self._finish_run(run_id, RunStatus.STOPPED)
                return
            remaining_seconds = PAPER_BETA.remaining_run_seconds(
                run.started_at, system_now_utc()
            )
            if remaining_seconds == 0:
                await self._execution_store.begin_stopping(run_id)
                await self._finish_run(
                    run_id, RunStatus.STOPPED, failure_detail=DURATION_EXPIRED_DETAIL
                )
                return
            bot_task = asyncio.create_task(
                run_claimed_bot(
                    run,
                    observer,
                    execution_scope=FillOwnership(
                        run_id, self._session_factory, self._lease
                    ).scope,
                )
            )
            cooperative_stop = asyncio.Event()
            monitor_task = asyncio.create_task(
                self._poll_stop_request_and_heartbeat(
                    run_id,
                    bot_task,
                    cooperative_stop,
                )
            )
            try:
                done, _ = await asyncio.wait(
                    (bot_task, monitor_task),
                    timeout=remaining_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    await self._execution_store.begin_stopping(run_id)
                    cooperative_stop.set()
                    bot_task.cancel()
                    failure_detail = DURATION_EXPIRED_DETAIL
                if monitor_task in done:
                    # Monitoring owns the stop lease; its failure must stop execution.
                    await monitor_task
                    if not bot_task.done() and not cooperative_stop.is_set():
                        raise RuntimeError("owned run monitoring ended unexpectedly")
                if not bot_task.done():
                    await asyncio.wait((bot_task,), timeout=RUNTIME_CLEANUP_SECONDS)
                if bot_task.done():
                    bot_task.result()
                else:
                    terminal_status = RunStatus.INTERRUPTED
            except asyncio.CancelledError:
                # Manual stop and duration expiry record cooperative cancellation;
                # Taskiq/process shutdown records lease interruption.
                if not cooperative_stop.is_set():
                    terminal_status = RunStatus.INTERRUPTED
                    propagate_cancellation = True
            finally:
                if not await self._shutdown_runtime_tasks(bot_task, monitor_task):
                    terminal_status = RunStatus.INTERRUPTED
        except asyncio.CancelledError:
            terminal_status = RunStatus.INTERRUPTED
            propagate_cancellation = True
        except (ExecutionOwnershipLost, SQLAlchemyError, TimeoutError):
            terminal_status = RunStatus.INTERRUPTED
        except TrackedMarketLimitExceeded:
            terminal_status = RunStatus.FAILED
            failure_detail = RunFailureReason.TRACKED_MARKET_ALLOWANCE
        except Exception as error:
            terminal_status = RunStatus.FAILED
            failure_detail = sanitized_failure_detail(error, PAPER_RUN_FAILURE_REASON)
        else:
            if terminal_status is RunStatus.STOPPED:
                await self._execution_store.begin_stopping(run_id)

        await self._finish_run(
            run_id,
            terminal_status,
            failure_detail=failure_detail,
        )
        if propagate_cancellation:
            raise asyncio.CancelledError

    async def _poll_stop_request_and_heartbeat(
        self,
        run_id: UUID,
        bot_task: asyncio.Task[None],
        cooperative_stop: asyncio.Event,
    ) -> None:
        while not bot_task.done():
            await asyncio.sleep(self._heartbeat_seconds)
            async with (
                asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS),
                self._session_factory() as session,
            ):
                store = RunStore(session).owned_by(self._lease)
                status = await store.status(run_id)
                if status is None:
                    raise ExecutionOwnershipLost(
                        "owned run disappeared while monitoring"
                    )
                if status is RunStatus.STOP_REQUESTED:
                    if await store.begin_stopping(run_id):
                        # Persist the transition before local cancellation so another
                        # process never has to infer why the bot stopped.
                        cooperative_stop.set()
                        bot_task.cancel()
                    return
                if not await store.heartbeat(run_id, now=system_now_utc()):
                    raise ExecutionOwnershipLost("paper execution lease was lost")

    async def _shutdown_runtime_tasks(self, *tasks: asyncio.Task[None]) -> bool:
        for task in tasks:
            task.cancel()
        done, pending = await asyncio.wait(tasks, timeout=RUNTIME_CLEANUP_SECONDS)
        for task in done:
            if not task.cancelled():
                task.exception()
        for task in pending:
            task.cancel()
        return not pending

    async def _finish_run(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        failure_detail: str | None = None,
    ) -> None:
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            await self._execution_store.finish(
                run_id,
                status=status,
                now=system_now_utc(),
                failure_detail=failure_detail,
            )
