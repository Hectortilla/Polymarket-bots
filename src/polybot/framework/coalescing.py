"""Keyed newest-value coalescing with stable first-marker ordering."""

from __future__ import annotations

from typing import Generic, TypeVar


KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


class PendingByKey(Generic[KeyT, ValueT]):
    def __init__(self) -> None:
        self._values: dict[KeyT, ValueT] = {}

    def update(self, key: KeyT, value: ValueT) -> bool:
        """Store the newest value and report whether a marker is required."""
        marker_required = key not in self._values
        self._values[key] = value
        return marker_required

    def pop(self, key: KeyT) -> ValueT:
        return self._values.pop(key)

    def __contains__(self, key: object) -> bool:
        return key in self._values
