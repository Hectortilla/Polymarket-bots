"""No-store response headers, including failures from inner middleware."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.http.protocol import (
    ASGI_HTTP_RESPONSE_START,
    ASGI_HTTP_SCOPE,
    ASGI_TYPE_FIELD,
    CACHE_CONTROL_HEADER,
    NO_STORE_CACHE_DIRECTIVE,
)

CACHE_CONTROL_ASGI_HEADER = CACHE_CONTROL_HEADER.lower().encode("ascii")
NO_STORE_ASGI_DIRECTIVE = NO_STORE_CACHE_DIRECTIVE.encode("ascii")


class PrivateResponseMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope[ASGI_TYPE_FIELD] != ASGI_HTTP_SCOPE:
            await self.app(scope, receive, send)
            return

        async def send_no_store_response(message: Message) -> None:
            if message[ASGI_TYPE_FIELD] == ASGI_HTTP_RESPONSE_START:
                message["headers"] = [
                    (key, value)
                    for key, value in message["headers"]
                    if key.lower() != CACHE_CONTROL_ASGI_HEADER
                ]
                message["headers"].append(
                    (CACHE_CONTROL_ASGI_HEADER, NO_STORE_ASGI_DIRECTIVE)
                )
            await send(message)

        await self.app(scope, receive, send_no_store_response)
