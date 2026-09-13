"""Dependency-light source identity contract shared by runtime and release tools."""

import re

RELEASE_ID_ENV = "POLYBOT_RELEASE_ID"
RELEASE_ID_PATTERN = r"[a-f0-9]{40,64}"


def validate_release_id(value: str) -> str:
    if re.fullmatch(RELEASE_ID_PATTERN, value) is None:
        raise ValueError("an immutable release ID is required")
    return value
