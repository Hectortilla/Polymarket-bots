from __future__ import annotations

class SourceEventDeduper:
    """Remember source IDs for the full lifetime of one runtime."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def claim_if_new(self, source_id: str) -> bool:
        if not source_id:
            return False
        if source_id in self._seen:
            return False

        self._seen.add(source_id)
        return True
