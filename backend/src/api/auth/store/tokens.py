"""Opaque session tokens: parse at cookie ingress, digest at persistence."""

import re
import secrets
from dataclasses import dataclass, field

from api.auth.policy import SESSION_TOKEN_BYTES
from api.auth.token_digest import digest_token_value

SESSION_TOKEN_LENGTH = (SESSION_TOKEN_BYTES * 8 + 5) // 6
SESSION_TOKEN_PATTERN = re.compile(rf"[A-Za-z0-9_-]{{{SESSION_TOKEN_LENGTH}}}\Z")


@dataclass(frozen=True)
class SessionToken:
    value: str = field(repr=False)

    @classmethod
    def parse(cls, value: str | None) -> "SessionToken | None":
        if value is None or SESSION_TOKEN_PATTERN.fullmatch(value) is None:
            return None
        return cls(value)

    @classmethod
    def issue(cls) -> "SessionToken":
        return cls(secrets.token_urlsafe(SESSION_TOKEN_BYTES))

    @property
    def digest(self) -> str:
        return digest_token_value(self.value)
