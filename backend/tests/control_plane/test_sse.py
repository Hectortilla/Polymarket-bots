import asyncio
import json
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from api.events.channels import (
    decode_durable_wake_frame,
    encode_durable_wake_frame,
    encode_live_event_frame,
)
from api.events.contracts import (
    EquityChartPayload,
    LiveEquityChartEvent,
    RunLifecycleEvent,
    RunStatusPayload,
)
from api.events.contracts.payloads.chart import EquityChartPointPayload
from api.events.ids import (
    FIRST_DURABLE_EVENT_ID,
    FIRST_EVENT_CURSOR,
    MAX_DURABLE_EVENT_ID,
    MAX_DURABLE_EVENT_ID_DIGITS,
)
from api.events.kinds import (
    EVENT_DISCRIMINATOR_FIELD,
    LiveEventKind,
)
from api.events.pagination import MAX_EVENT_PAGE_LIMIT
from api.http.sse import RunEventStreamer
from api.http.sse.frames import (
    SSE_DATA_FIELD,
    SSE_FIELD_SEPARATOR,
    SSE_ID_FIELD,
    SSE_IDLE_COMMENT,
)
from api.http.sse.replay import RunEventReplay
from api.runs.status import RunStatus
from polybot.performance.contracts.valuation_status import ValuationStatus
from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError


def test_durable_wake_frame_is_strict_positive_bigint_ascii() -> None:
    assert encode_durable_wake_frame(MAX_DURABLE_EVENT_ID) == str(MAX_DURABLE_EVENT_ID)
    with pytest.raises(ValueError):
        encode_durable_wake_frame(FIRST_DURABLE_EVENT_ID - 1)
    with pytest.raises(ValueError):
        encode_durable_wake_frame(MAX_DURABLE_EVENT_ID + 1)
    assert decode_durable_wake_frame(b"42") == 42
    assert decode_durable_wake_frame("42") == 42
    for invalid in (
        b"",
        str(FIRST_DURABLE_EVENT_ID - 1).encode(),
        b"+1",
        b" 1",
        b"1\n",
        "N{ARABIC-INDIC DIGIT ONE}",
        str(MAX_DURABLE_EVENT_ID + 1),
        1,
        b"1" * (MAX_DURABLE_EVENT_ID_DIGITS + 1),
    ):
        assert decode_durable_wake_frame(invalid) is None


def test_terminal_initial_replay_does_not_subscribe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    pubsub = _PubSub(())
    redis = _Redis(pubsub)

    async def read_events(*args, **kwargs):
        return (_event(run_id, 1, RunStatus.STOPPED),)

    monkeypatch.setattr(RunEventReplay, "read", read_events)

    frames = asyncio.run(_collect(run_id, redis))

    assert tuple(_frame_id(frame) for frame in frames) == (1,)
    assert redis.pubsub_requested is False


def test_persisted_event_without_id_is_rejected_at_sse_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    pubsub = _PubSub(())
    redis = _Redis(pubsub)

    async def read_events(*args, **kwargs):
        return (
            RunLifecycleEvent(
                run_id=run_id,
                occurred_at=datetime.now(UTC),
                payload=RunStatusPayload(status=RunStatus.RUNNING),
            ),
        )

    monkeypatch.setattr(RunEventReplay, "read", read_events)

    with pytest.raises(ValueError, match="missing its ID"):
        asyncio.run(_collect(run_id, redis))
    assert redis.pubsub_requested is False


def test_replay_recheck_and_wake_share_the_latest_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    pubsub = _PubSub((None, {"data": b"3"}))
    redis = _Redis(pubsub)
    reads = iter(
        (
            (_event(run_id, 1, RunStatus.RUNNING),),
            (_event(run_id, 2, RunStatus.RUNNING),),
            (_event(run_id, 3, RunStatus.STOPPED),),
        )
    )
    cursors: list[int] = []

    async def read_events(*args, after_event_id: int, **kwargs):
        cursors.append(after_event_id)
        return next(reads)

    monkeypatch.setattr(RunEventReplay, "read", read_events)

    frames = asyncio.run(_collect(run_id, redis))

    assert tuple(_frame_id(frame) for frame in frames if not frame.startswith(":")) == (
        1,
        2,
        3,
    )
    assert SSE_IDLE_COMMENT in frames
    assert cursors == [0, 1, 2]


def test_replay_subscribe_recheck_delivers_handoff_event_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    pubsub = _PubSub([])
    redis = _Redis(pubsub)
    reads = iter(
        (
            (_event(run_id, 1, RunStatus.RUNNING),),
            (_event(run_id, 2, RunStatus.STOPPED),),
        )
    )

    async def read_events(*args, **kwargs):
        return next(reads)

    monkeypatch.setattr(RunEventReplay, "read", read_events)

    frames = asyncio.run(_collect(run_id, redis))

    assert tuple(_frame_id(frame) for frame in frames) == (1, 2)
    assert pubsub.subscribed is True
    assert pubsub.unsubscribed is True
    assert pubsub.closed is True


def test_initial_replay_reads_large_backlog_in_bounded_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    terminal_id = MAX_EVENT_PAGE_LIMIT * 2 + 1
    events = tuple(
        _event(
            run_id,
            event_id,
            RunStatus.STOPPED if event_id == terminal_id else RunStatus.RUNNING,
        )
        for event_id in range(1, terminal_id + 1)
    )
    cursors: list[int] = []

    async def read_events(*args, after_event_id: int, **kwargs):
        cursors.append(after_event_id)
        return events[after_event_id : after_event_id + MAX_EVENT_PAGE_LIMIT]

    redis = _Redis(_PubSub(()))
    monkeypatch.setattr(RunEventReplay, "read", read_events)

    frames = asyncio.run(_collect(run_id, redis))

    assert len(frames) == terminal_id
    assert cursors == [0, MAX_EVENT_PAGE_LIMIT, MAX_EVENT_PAGE_LIMIT * 2]
    assert redis.pubsub_requested is False


def test_malformed_wake_is_dropped_before_valid_terminal_wake(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_id = uuid4()
    pubsub = _PubSub(({"data": b"bad"}, {"data": b"2"}))
    redis = _Redis(pubsub)
    reads = iter(((), (), (_event(run_id, 2, RunStatus.FAILED),)))

    async def read_events(*args, **kwargs):
        return next(reads)

    monkeypatch.setattr(RunEventReplay, "read", read_events)
    caplog.set_level(logging.WARNING)

    frames = asyncio.run(_collect(run_id, redis))

    assert tuple(_frame_id(frame) for frame in frames) == (2,)
    assert "dropping malformed run event frame" in caplog.text
    assert pubsub.closed is True


def test_live_frame_has_no_cursor_and_durable_continuation_keeps_its_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    live = LiveEquityChartEvent(
        run_id=run_id,
        occurred_at=datetime.now(UTC),
        payload=EquityChartPayload(
            sampled_at_ms=1_000,
            point=EquityChartPointPayload(
                value="101.5",
                status=ValuationStatus.FRESH,
            ),
        ),
    )
    pubsub = _PubSub(({"data": encode_live_event_frame(live)}, {"data": b"2"}))
    reads = iter(((), (), (_event(run_id, 2, RunStatus.STOPPED),)))

    async def read_events(*args, **kwargs):
        return next(reads)

    monkeypatch.setattr(RunEventReplay, "read", read_events)
    frames = asyncio.run(_collect(run_id, _Redis(pubsub)))

    data_prefix = f"{SSE_DATA_FIELD}{SSE_FIELD_SEPARATOR}"
    id_prefix = f"{SSE_ID_FIELD}{SSE_FIELD_SEPARATOR}"
    assert frames[0].startswith(data_prefix)
    assert not frames[0].startswith(id_prefix)
    assert (
        json.loads(frames[0].split(data_prefix, 1)[1])[EVENT_DISCRIMINATOR_FIELD]
        == LiveEventKind.CHART_EQUITY.value
    )
    assert _frame_id(frames[1]) == 2


def test_live_event_for_another_run_is_dropped_before_target_continues(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_id = uuid4()
    wrong_run_event = LiveEquityChartEvent(
        run_id=uuid4(),
        occurred_at=datetime.now(UTC),
        payload=EquityChartPayload(
            sampled_at_ms=1_000,
            point=EquityChartPointPayload(
                value="101.5",
                status=ValuationStatus.FRESH,
            ),
        ),
    )
    pubsub = _PubSub(
        ({"data": encode_live_event_frame(wrong_run_event)}, {"data": b"2"})
    )
    reads = iter(((), (), (_event(run_id, 2, RunStatus.STOPPED),)))

    async def read_events(*args, **kwargs):
        return next(reads)

    monkeypatch.setattr(RunEventReplay, "read", read_events)
    caplog.set_level(logging.WARNING)

    frames = asyncio.run(_collect(run_id, _Redis(pubsub)))

    assert tuple(_frame_id(frame) for frame in frames) == (2,)
    assert "dropping malformed run event frame" in caplog.text


def test_disconnect_releases_pubsub_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    pubsub = _PubSub([])
    redis = _Redis(pubsub)

    async def read_events(*args, **kwargs):
        return ()

    monkeypatch.setattr(RunEventReplay, "read", read_events)

    frames = asyncio.run(_collect(run_id, redis, disconnected=True))

    assert frames == []
    assert pubsub.unsubscribed is True
    assert pubsub.closed is True


def test_redis_failure_ends_stream_and_releases_subscription(monkeypatch, caplog):
    pubsub = _PubSub([])
    monkeypatch.setattr(RunEventReplay, "read", AsyncMock(return_value=()))
    monkeypatch.setattr(
        pubsub,
        "get_message",
        AsyncMock(side_effect=RedisError("private infrastructure detail")),
    )
    with caplog.at_level(logging.ERROR):
        assert asyncio.run(_collect(uuid4(), _Redis(pubsub))) == []
    assert pubsub.unsubscribed and pubsub.closed
    assert "required service is unavailable" in caplog.text
    assert "private infrastructure detail" not in caplog.text



def test_database_replay_failure_is_sanitized_before_subscribing(monkeypatch, caplog):
    pubsub = _PubSub([])
    redis = _Redis(pubsub)
    failure = OperationalError("private SQL", {}, Exception("private database detail"))
    monkeypatch.setattr(RunEventReplay, "read", AsyncMock(side_effect=failure))
    with caplog.at_level(logging.ERROR):
        assert asyncio.run(_collect(uuid4(), redis)) == []
    assert not redis.pubsub_requested
    assert "required service is unavailable" in caplog.text
    assert "private" not in caplog.text


async def _collect(
    run_id: UUID,
    redis: "_Redis",
    *,
    disconnected: bool = False,
) -> list[str]:
    return [
        frame
        async for frame in RunEventStreamer(
            run_id,
            _Request(disconnected),
            object(),
            redis,
            AsyncMock(allowed=AsyncMock(return_value=True)),
        ).stream(FIRST_EVENT_CURSOR)
    ]


def _event(run_id: UUID, event_id: int, status: RunStatus) -> RunLifecycleEvent:
    return RunLifecycleEvent(
        id=event_id,
        run_id=run_id,
        occurred_at=datetime.now(UTC),
        payload=RunStatusPayload(status=status),
    )


def _frame_id(frame: str) -> int:
    first_line = frame.splitlines()[0]
    return int(first_line.removeprefix(f"{SSE_ID_FIELD}{SSE_FIELD_SEPARATOR}"))


class _Request:
    def __init__(self, disconnected: bool) -> None:
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


class _Redis:
    def __init__(self, pubsub: "_PubSub") -> None:
        self._pubsub = pubsub
        self.pubsub_requested = False

    def pubsub(self) -> "_PubSub":
        self.pubsub_requested = True
        return self._pubsub


class _PubSub:
    def __init__(self, messages) -> None:
        self.messages = iter(messages)
        self.subscribed = False
        self.unsubscribed = False
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed = True

    async def get_message(self, **kwargs):
        return next(self.messages)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed = True

    async def aclose(self) -> None:
        self.closed = True
