import asyncio

from polybot.cli.observability.activity import ObserverActivitySink
from polybot.cli.observability.observer import RuntimeObserver
from polybot.framework.activity import ActivitySeverity, BotActivityEvent, NullActivitySink
from polybot.framework.config.models import BotConfig


class RecordingObserver(RuntimeObserver):
    def __init__(self) -> None:
        self.events: list[object] = []

    async def start(self, config: BotConfig) -> None:
        return None

    def emit(self, event: object) -> None:
        self.events.append(event)

    async def stop(self) -> None:
        return None


class FailingObserver(RuntimeObserver):
    async def start(self, config: BotConfig) -> None:
        return None

    def emit(self, event: object) -> None:
        raise RuntimeError("observer failed")

    async def stop(self) -> None:
        return None


def test_null_activity_sink_is_awaitable() -> None:
    asyncio.run(NullActivitySink().emit("ignored"))


def test_observer_activity_sink_emits_typed_event() -> None:
    async def run() -> RecordingObserver:
        observer = RecordingObserver()
        await ObserverActivitySink(observer).emit(
            "signal confirmed",
            severity=ActivitySeverity.SUCCESS,
        )
        return observer

    observer = asyncio.run(run())

    assert len(observer.events) == 1
    event = observer.events[0]
    assert isinstance(event, BotActivityEvent)
    assert event.message == "signal confirmed"
    assert event.severity is ActivitySeverity.SUCCESS


def test_activity_sink_drops_invalid_input_and_observer_failures() -> None:
    async def run() -> None:
        recording_observer = RecordingObserver()
        await ObserverActivitySink(recording_observer).emit("   ")
        assert recording_observer.events == []

        await ObserverActivitySink(FailingObserver()).emit("visible")

    asyncio.run(run())
