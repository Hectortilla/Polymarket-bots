"""Availability states shared by runtime values and response contracts."""

from enum import StrEnum


class GraphValueStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    INVALID = "invalid"
    SKIPPED = "skipped"
    PLANNED = "planned"
