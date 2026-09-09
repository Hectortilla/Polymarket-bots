"""Shared digest representation for opaque authentication credentials."""

import hashlib

AUTH_TOKEN_DIGEST_HEX_LENGTH = hashlib.sha256().digest_size * 2


def digest_token_value(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()
