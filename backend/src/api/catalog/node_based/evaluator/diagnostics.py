"""Per-node activity coalescing without changing trading outcomes."""

from dataclasses import dataclass

from polybot.framework.context import BotContext

DIAGNOSTIC_INTERVAL_MS = 1000


@dataclass(slots=True)
class _LastMessage:
    message: str
    emitted_at_ms: int
    suppressed: int = 0


class GraphDiagnostics:
    def __init__(self) -> None:
        self._last: dict[str, _LastMessage] = {}

    async def emit(self, ctx: BotContext, node_id: str, message: str) -> None:
        now_ms = ctx.clock.now_ms()
        previous = self._last.get(node_id)
        if (
            previous is not None
            and previous.message == message
            and now_ms - previous.emitted_at_ms < DIAGNOSTIC_INTERVAL_MS
        ):
            previous.suppressed += 1
            return
        suffix = (
            f" ({previous.suppressed} repeated messages suppressed)"
            if previous is not None and previous.suppressed
            else ""
        )
        self._last[node_id] = _LastMessage(message, now_ms)
        await ctx.activity.emit(f"[{node_id}] {message}{suffix}")
