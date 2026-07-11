from __future__ import annotations

from collections import deque


class SourceEventDeduper:
    def __init__(self, max_seen: int = 10_000) -> None:
        self.max_seen = max_seen
        self._seen: set[str] = set()
        self._order: deque[str] = deque()

    def remember(self, source_id: str) -> bool:
        if not source_id:
            return False
        if source_id in self._seen:
            return False

        self._seen.add(source_id)
        self._order.append(source_id)
        self._trim()
        return True

    def _trim(self) -> None:
        while len(self._order) > self.max_seen:
            expired = self._order.popleft()
            self._seen.discard(expired)
