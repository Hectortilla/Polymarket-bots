"""Bounded, single-delivery ASGI request buffering for credential ingress."""

from dataclasses import dataclass

from fastapi import HTTPException, status
from starlette.types import Message, Receive

from api.auth.policy import AUTH_BODY_MAX_BYTES, AUTH_BODY_TOO_LARGE_DETAIL
from api.http.protocol import (
    ASGI_BODY_FIELD,
    ASGI_HTTP_DISCONNECT,
    ASGI_HTTP_REQUEST,
    ASGI_MORE_BODY_FIELD,
    ASGI_TYPE_FIELD,
)


@dataclass
class AuthRequestBody:
    content: bytes
    receive_remaining: Receive
    delivered: bool = False

    @classmethod
    async def read(cls, receive: Receive) -> "AuthRequestBody | None":
        body = bytearray()
        while True:
            message = await receive()
            if message[ASGI_TYPE_FIELD] == ASGI_HTTP_DISCONNECT:
                return None
            body.extend(message.get(ASGI_BODY_FIELD, b""))
            if len(body) > AUTH_BODY_MAX_BYTES:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE, AUTH_BODY_TOO_LARGE_DETAIL
                )
            if not message.get(ASGI_MORE_BODY_FIELD, False):
                return cls(bytes(body), receive)

    async def receive(self) -> Message:
        if self.delivered:
            return await self.receive_remaining()
        self.delivered = True
        return {
            ASGI_TYPE_FIELD: ASGI_HTTP_REQUEST,
            ASGI_BODY_FIELD: self.content,
            ASGI_MORE_BODY_FIELD: False,
        }
