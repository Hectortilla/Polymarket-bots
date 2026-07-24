"""Keyed newest-value coalescing with stable first-marker ordering."""

from __future__ import annotations

from collections.abc import Callable
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

    def discard(self, key: KeyT) -> bool:
        """Discard a pending value and report whether it was present."""
        return self._values.pop(key, None) is not None

    def discard_matching(self, predicate: Callable[[ValueT], bool]) -> int:
        """Discard every pending value selected by ``predicate``."""
        return len(self.discard_matching_keys(predicate))

    def discard_matching_keys(
        self,
        predicate: Callable[[ValueT], bool],
    ) -> tuple[KeyT, ...]:
        """Discard selected values and return their keys."""
        keys = tuple(
            key for key, value in self._values.items() if predicate(value)
        )
        for key in keys:
            del self._values[key]
        return keys

    def __contains__(self, key: object) -> bool:
        return key in self._values
