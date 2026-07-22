"""Optional book-continuity guard used by deterministic replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BookContinuity:
    revision: int
    blackout: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("book continuity revision must be nonnegative")
        if not isinstance(self.blackout, bool):
            raise ValueError("book continuity blackout state must be boolean")


class BookContinuitySource(Protocol):
    def book_continuity(self, token_id: str) -> BookContinuity | None: ...
