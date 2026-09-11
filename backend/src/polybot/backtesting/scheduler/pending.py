"""Ordered replay events with per-token book coalescing and blackout removal."""

from collections import deque
from dataclasses import dataclass

from polybot.framework.coalescing import PendingByKey
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent


@dataclass(frozen=True, slots=True)
class _BookMarker:
    token_id: str


class PendingReplayEvents:
    def __init__(self) -> None:
        self._markers: deque[_BookMarker | MarketResolutionEvent] = deque()
        self._books: PendingByKey[str, BookSnapshot] = PendingByKey()

    def enqueue_books(self, books: tuple[BookSnapshot, ...]) -> None:
        for book in books:
            if self._books.update(book.token_id, book):
                self._markers.append(_BookMarker(book.token_id))

    def enqueue_resolution(self, event: MarketResolutionEvent) -> None:
        self._markers.append(event)

    def pop(self) -> BookSnapshot | MarketResolutionEvent | None:
        if not self._markers:
            return None
        marker = self._markers.popleft()
        return (
            self._books.pop(marker.token_id)
            if isinstance(marker, _BookMarker)
            else marker
        )

    def invalidate_books(self, token_ids: set[str]) -> None:
        for token_id in token_ids:
            self._books.discard(token_id)
        self._markers = deque(
            marker
            for marker in self._markers
            if not (isinstance(marker, _BookMarker) and marker.token_id in token_ids)
        )
