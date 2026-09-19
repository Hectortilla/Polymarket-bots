"""Replay ordering and authorization at the SSE/hub boundary."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from api.events.channels import decode_durable_wake_frame, encode_durable_wake_frame
from api.events.contracts import RunLifecycleEvent, RunStatusPayload
from api.events.delivery import EventDelivery
from api.events.ids import MAX_DURABLE_EVENT_ID
from api.events.pagination import MAX_EVENT_PAGE_LIMIT
from api.http.sse import RunEventStreamer
from api.http.sse import __name__ as STREAM_MODULE
from api.http.sse.frames import SSE_IDLE_COMMENT
from api.http.sse.mailbox import LiveFrame, ViewerMailbox
from api.http.sse.replay import RunEventReplay
from api.runs.status import RunStatus
from sqlalchemy.exc import OperationalError


def test_durable_wake_frame_is_strict_positive_bigint_ascii():
    assert (
        decode_durable_wake_frame(encode_durable_wake_frame(MAX_DURABLE_EVENT_ID))
        == MAX_DURABLE_EVENT_ID
    )
    for invalid in (
        b"",
        "0",
        b"+1",
        b" 1",
        b"1\n",
        "١",
        str(MAX_DURABLE_EVENT_ID + 1),
        1,
    ):
        assert decode_durable_wake_frame(invalid) is None
    for invalid in (0, MAX_DURABLE_EVENT_ID + 1):
        with pytest.raises(ValueError):
            encode_durable_wake_frame(invalid)


def test_terminal_initial_replay_does_not_attach(monkeypatch):
    run = uuid4()
    monkeypatch.setattr(
        RunEventReplay,
        "read",
        AsyncMock(return_value=(_event(run, 1, RunStatus.STOPPED),)),
    )
    hub = _Hub()
    frames = asyncio.run(_collect(run, hub))
    assert len(frames) == 1 and frames[0].startswith("id: 1")
    assert not hub.attached


def test_missing_durable_id_is_rejected(monkeypatch):
    event = _event(uuid4(), None, RunStatus.RUNNING)
    monkeypatch.setattr(RunEventReplay, "read", AsyncMock(return_value=(event,)))
    with pytest.raises(ValueError, match="missing its ID"):
        asyncio.run(_collect(event.event.run_id, _Hub()))


def test_handoff_recheck_and_wake_share_latest_cursor(monkeypatch):
    run = uuid4()
    cursors = []

    async def read(self, after_event_id):
        cursors.append(after_event_id)
        return (
            _event(
                run,
                after_event_id + 1,
                RunStatus.STOPPED if after_event_id == 2 else RunStatus.RUNNING,
            ),
        )

    monkeypatch.setattr(RunEventReplay, "read", read)
    hub = _Hub(wake=True)
    frames = asyncio.run(_collect(run, hub))
    assert [frame.splitlines()[0] for frame in frames] == ["id: 1", "id: 2", "id: 3"]
    assert cursors == [0, 1, 2]
    assert hub.detached and hub.terminal_seen


def test_large_initial_backlog_is_bounded(monkeypatch):
    run = uuid4()
    last = MAX_EVENT_PAGE_LIMIT * 2 + 1
    events = tuple(
        _event(run, i, RunStatus.STOPPED if i == last else RunStatus.RUNNING)
        for i in range(1, last + 1)
    )
    cursors = []

    async def read(self, after_event_id):
        cursors.append(after_event_id)
        return events[after_event_id : after_event_id + MAX_EVENT_PAGE_LIMIT]

    monkeypatch.setattr(RunEventReplay, "read", read)
    hub = _Hub()
    assert len(asyncio.run(_collect(run, hub))) == last
    assert cursors == [0, MAX_EVENT_PAGE_LIMIT, MAX_EVENT_PAGE_LIMIT * 2]
    assert not hub.attached


def test_continuous_live_cannot_starve_reconciliation(monkeypatch):
    async def scenario():
        run = uuid4()
        calls = 0

        async def read(*args, **kwargs):
            nonlocal calls
            calls += 1
            return (_event(run, 1, RunStatus.STOPPED),) if calls >= 3 else ()

        monkeypatch.setattr(RunEventReplay, "read", read)
        monkeypatch.setattr(STREAM_MODULE + ".SSE_RECONCILIATION_SECONDS", 0.03)
        hub = _Hub()

        async def flood():
            while True:
                hub.mailbox.offer_live(_live())
                await asyncio.sleep(0.001)

        producer = asyncio.create_task(flood())
        try:
            frames = await asyncio.wait_for(_collect(run, hub), 0.5)
            assert any(isinstance(frame, bytes) for frame in frames)
            assert frames[-1].startswith("id: 1")
            assert hub.terminal_seen and hub.detached
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    asyncio.run(scenario())


def test_durable_wake_takes_precedence_over_pending_live(monkeypatch):
    run = uuid4()
    monkeypatch.setattr(
        RunEventReplay,
        "read",
        AsyncMock(side_effect=[(), (), (_event(run, 1, RunStatus.STOPPED),)]),
    )
    hub = _Hub(wake=True)
    hub.mailbox.offer_live(_live())
    frames = asyncio.run(_collect(run, hub))
    assert len(frames) == 1 and frames[0].startswith("id: 1")


def test_authorization_revocation_drops_pending_live_and_detaches(monkeypatch):
    monkeypatch.setattr(RunEventReplay, "read", AsyncMock(return_value=()))
    hub = _Hub()
    hub.mailbox.offer_live(_live())
    authorization = SimpleNamespace(allowed=AsyncMock(side_effect=[True, True, False]))
    assert asyncio.run(_collect(uuid4(), hub, authorization=authorization)) == []
    assert hub.detached


def test_expiry_after_authorization_drops_live(monkeypatch):
    async def scenario():
        monkeypatch.setattr(RunEventReplay, "read", AsyncMock(return_value=()))
        hub = _Hub()
        frame = _live()
        hub.mailbox.offer_live(frame)

        async def allowed():
            if hub.attached:
                frame.clock.valid = False
                hub.mailbox.close()
            return True

        assert (
            await _collect(uuid4(), hub, authorization=SimpleNamespace(allowed=allowed))
            == []
        )

    asyncio.run(scenario())


def test_other_viewer_terminal_during_authorization_drops_dequeued_live(monkeypatch):
    async def scenario():
        run, hub = uuid4(), _Hub()

        async def frames(self, cursor):
            yield _live(), False

        async def allowed():
            hub.terminal(run)
            return True

        monkeypatch.setattr(RunEventStreamer, "_stream_frames", frames)
        assert (
            await _collect(run, hub, authorization=SimpleNamespace(allowed=allowed))
            == []
        )

    asyncio.run(scenario())


def test_disconnect_releases_mailbox(monkeypatch):
    monkeypatch.setattr(RunEventReplay, "read", AsyncMock(return_value=()))
    hub = _Hub()
    assert asyncio.run(_collect(uuid4(), hub, disconnected=True)) == []
    assert hub.detached


def test_database_failure_is_sanitized(monkeypatch, caplog):
    failure = OperationalError("private SQL", {}, Exception("private detail"))
    monkeypatch.setattr(RunEventReplay, "read", AsyncMock(side_effect=failure))
    assert asyncio.run(_collect(uuid4(), _Hub())) == []
    assert "required service is unavailable" in caplog.text
    assert "private" not in caplog.text


def _event(run, event_id, status):
    return EventDelivery(
        RunLifecycleEvent(
            id=event_id,
            run_id=run,
            occurred_at=datetime.now(UTC),
            payload=RunStatusPayload(status=status),
        ),
        False,
    )


def _live():
    clock = SimpleNamespace(epoch=0, valid=True)
    clock.fresh = lambda _: clock.valid
    return LiveFrame(b"data: {}\n\n", 1, clock, 0)


class _Hub:
    def __init__(self, wake=False):
        self.mailbox = ViewerMailbox()
        self.attached = self.detached = self.terminal_seen = False
        if wake:
            self.mailbox.offer_durable_wake()

    async def attach(self, run):
        self.attached = True
        return self.mailbox

    async def detach(self, run, mailbox):
        self.detached = True
        mailbox.close()

    def terminal(self, run):
        self.terminal_seen = True
        self.mailbox.terminal()

    def is_terminal(self, run):
        return self.terminal_seen


async def _collect(run, hub, *, disconnected=False, authorization=None):
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=disconnected))
    authorization = authorization or SimpleNamespace(
        allowed=AsyncMock(return_value=True)
    )
    return [
        frame
        async for frame in RunEventStreamer(
            run, request, object(), authorization, hub=hub
        ).stream(0)
        if frame != SSE_IDLE_COMMENT
    ]


def test_idle_stream_flushes_a_comment_before_waiting(monkeypatch):
    async def scenario():
        monkeypatch.setattr(RunEventReplay, "read", AsyncMock(return_value=()))
        hub = _Hub()
        stream = RunEventStreamer(
            uuid4(),
            SimpleNamespace(is_disconnected=AsyncMock(return_value=False)),
            object(),
            SimpleNamespace(allowed=AsyncMock(return_value=True)),
            hub=hub,
        ).stream(0)
        assert await asyncio.wait_for(anext(stream), 0.5) == SSE_IDLE_COMMENT
        await stream.aclose()
        assert hub.detached

    asyncio.run(scenario())
