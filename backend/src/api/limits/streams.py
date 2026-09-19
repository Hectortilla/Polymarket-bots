"""Bounded SSE lifetime, including slow sends and source cleanup."""

from collections.abc import AsyncGenerator

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Message, Send

from api.events.live.metrics import LiveMetric, LiveMetrics
from api.http.protocol import (
    ASGI_BODY_FIELD,
    ASGI_HTTP_RESPONSE_BODY,
    ASGI_HTTP_RESPONSE_START,
    ASGI_MORE_BODY_FIELD,
    ASGI_TYPE_FIELD,
)
from api.http.sse.policy import SSE_SEND_TIMEOUT_SECONDS
from api.limits.redis.stream_admission import StreamLease

STREAM_CLOSE_TIMEOUT_SECONDS = 1


class LimitedStreamResponse(StreamingResponse):
    def __init__(
        self,
        content: AsyncGenerator[str | bytes, None],
        lease: StreamLease,
        *,
        media_type: str,
        metrics: LiveMetrics | None = None,
    ) -> None:
        super().__init__(content, media_type=media_type)
        self._metrics = metrics
        self._content = content
        self._monotonic_deadline_seconds = lease.monotonic_deadline_seconds

    async def stream_response(self, send: Send) -> None:
        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            with anyio.fail_after(SSE_SEND_TIMEOUT_SECONDS):
                await send(message)
            if message[ASGI_TYPE_FIELD] == ASGI_HTTP_RESPONSE_START:
                response_started = True

        try:
            # One deadline bounds source iteration and slow client sends so neither
            # can retain the reservation beyond the stream lifetime.
            with anyio.move_on_after(
                max(0, self._monotonic_deadline_seconds - anyio.current_time())
            ) as lifetime:
                await super().stream_response(tracked_send)
            if lifetime.cancel_called:
                if not response_started:
                    raise TimeoutError("stream admission expired before response start")
                with anyio.move_on_after(STREAM_CLOSE_TIMEOUT_SECONDS):
                    await send(
                        {
                            ASGI_TYPE_FIELD: ASGI_HTTP_RESPONSE_BODY,
                            ASGI_BODY_FIELD: b"",
                            ASGI_MORE_BODY_FIELD: False,
                        }
                    )
        except TimeoutError:
            if self._metrics is not None:
                self._metrics.increment(LiveMetric.SLOW_CLIENT)
            raise
        finally:
            with anyio.fail_after(STREAM_CLOSE_TIMEOUT_SECONDS, shield=True):
                await self._content.aclose()
