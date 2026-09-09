"""Opaque account-link tokens, independent of browser session credentials."""

import re
import secrets
from dataclasses import dataclass, field

from api.auth.recovery.policy import ACCOUNT_TOKEN_ENTROPY_BYTES
from api.auth.token_digest import digest_token_value

# Unpadded URL-safe base64 length; parsing and ingress bounds share this value.
ACCOUNT_TOKEN_LENGTH = (ACCOUNT_TOKEN_ENTROPY_BYTES * 8 + 5) // 6
ACCOUNT_TOKEN_PATTERN = rf"[A-Za-z0-9_-]{{{ACCOUNT_TOKEN_LENGTH}}}"


@dataclass(frozen=True)
class AccountToken:
    value: str = field(repr=False)

    @classmethod
    def parse(cls, value: str) -> "AccountToken":
        if re.fullmatch(ACCOUNT_TOKEN_PATTERN, value) is None:
            raise ValueError("invalid account token")
        return cls(value)

    @classmethod
    def issue(cls) -> "AccountToken":
        return cls(secrets.token_urlsafe(ACCOUNT_TOKEN_ENTROPY_BYTES))

    @property
    def digest(self) -> str:
        return digest_token_value(self.value)
