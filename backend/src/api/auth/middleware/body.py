"""Bounded, single-delivery ASGI request buffering for credential ingress."""

from dataclasses import dataclass

from fastapi import HTTPException, status
from starlette.types import Message, Receive

from api.auth.policy import AUTH_BODY_MAX_BYTES, AUTH_BODY_TOO_LARGE_DETAIL


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
            if message["type"] == "http.disconnect":
                return None
            body.extend(message.get("body", b""))
            if len(body) > AUTH_BODY_MAX_BYTES:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE, AUTH_BODY_TOO_LARGE_DETAIL
                )
            if not message.get("more_body", False):
                return cls(bytes(body), receive)

    async def receive(self) -> Message:
        if self.delivered:
            return await self.receive_remaining()
        self.delivered = True
        return {"type": "http.request", "body": self.content, "more_body": False}
