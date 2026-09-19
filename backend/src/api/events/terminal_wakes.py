"""Bounded best-effort terminal notifications, admitted only after SQL commit."""

import asyncio
from collections import deque
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import event
from sqlalchemy.orm import Session, SessionTransaction

from api.events.writer import publish_durable_wake
from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.operations.observations.contracts import FailureObservation, Observation
from api.operations.observations.sink import OPERATION_LOG

TERMINAL_WAKE_LIMIT = 1024
_SINK_KEY = "terminal_wake_sink"
_PENDING_KEY = "terminal_wake_pending"


class TerminalWakePublisher:
    def __init__(self, sessions, redis: Redis) -> None:
        self._sessions, self._redis = sessions, redis
        self._previous_info = dict(sessions.kw.get("info", {}))
        self._pending: asyncio.Queue[tuple[UUID, int]] = asyncio.Queue(
            TERMINAL_WAKE_LIMIT
        )
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._sessions.configure(info={**self._previous_info, _SINK_KEY: self})
        self._task = asyncio.create_task(self._serve())

    async def close(self) -> None:
        self._sessions.configure(info=self._previous_info)
        try:
            async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                await self._pending.join()
        except TimeoutError:
            self._failure()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def offer(self, wake: tuple[UUID, int]) -> None:
        try:
            self._pending.put_nowait(wake)
        except asyncio.QueueFull:
            self._failure()

    @staticmethod
    def stage(session: Session, run_id: UUID, event_id: int) -> None:
        if _SINK_KEY not in session.info:
            return
        pending = session.info.setdefault(_PENDING_KEY, deque())
        if len(pending) == TERMINAL_WAKE_LIMIT:
            TerminalWakePublisher._failure()
            return
        transaction = session.get_nested_transaction() or session.get_transaction()
        pending.append((transaction, run_id, event_id))

    async def _serve(self) -> None:
        while True:
            run_id, event_id = await self._pending.get()
            try:
                async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                    await publish_durable_wake(self._redis, run_id, event_id)
            except Exception:
                self._failure()
            finally:
                self._pending.task_done()

    @staticmethod
    def _failure() -> None:
        OPERATION_LOG.emit(FailureObservation(Observation.TELEMETRY_UNAVAILABLE))


@event.listens_for(Session, "after_commit")
def _committed(session: Session) -> None:
    transaction = session.get_nested_transaction()
    if transaction is not None:
        # A released savepoint is not durable yet. Promote only its hints to
        # the enclosing transaction; a later rollback must still discard them.
        pending = session.info.get(_PENDING_KEY)
        if pending is not None:
            session.info[_PENDING_KEY] = deque(
                (
                    transaction.parent if owner is transaction else owner,
                    run_id,
                    event_id,
                )
                for owner, run_id, event_id in pending
            )
        return
    sink = session.info.get(_SINK_KEY)
    pending = session.info.pop(_PENDING_KEY, ())
    if sink is not None:
        for _, run_id, event_id in pending:
            sink.offer((run_id, event_id))


@event.listens_for(Session, "after_rollback")
def _rolled_back(session: Session) -> None:
    transaction = session.get_nested_transaction()
    if transaction is None:
        session.info.pop(_PENDING_KEY, None)
    elif _PENDING_KEY in session.info:
        session.info[_PENDING_KEY] = deque(
            entry for entry in session.info[_PENDING_KEY] if entry[0] is not transaction
        )


@event.listens_for(Session, "after_transaction_end")
def _transaction_ended(session: Session, transaction: SessionTransaction) -> None:
    # Session.close() rolls back without firing after_rollback. A reused session
    # must not publish those abandoned hints on an unrelated later commit.
    if transaction.parent is None:
        session.info.pop(_PENDING_KEY, None)
