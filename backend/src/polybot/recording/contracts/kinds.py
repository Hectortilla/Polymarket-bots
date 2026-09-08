"""Recording payload discriminators and their durable semantics."""

from __future__ import annotations

from enum import StrEnum


class PayloadKind(StrEnum):
    MARKET_METADATA = "market_metadata"
    BOOK_BASELINE = "book_baseline"
    BOOK_DELTA = "book_delta"
    PUBLIC_TRADE = "public_trade"
    TICK_SIZE_CHANGE = "tick_size_change"
    RESOLUTION = "resolution"
    COVERAGE_GAP = "coverage_gap"

    @property
    def event_count_field(self) -> str:
        """Return the matching field on ``RecordingEventCounts``."""
        return self.value

    @property
    def is_replay_event(self) -> bool:
        """Whether this payload is replayed as market state instead of metadata."""
        return self is not PayloadKind.COVERAGE_GAP

    @property
    def affects_book_state(self) -> bool:
        """Whether this payload can invalidate or advance a reconstructed book."""
        return self is not PayloadKind.PUBLIC_TRADE


BOOK_STATE_PAYLOAD_KINDS = tuple(
    kind for kind in PayloadKind if kind.affects_book_state
)


def payload_kind_sql_literals() -> str:
    """Return the discriminator literals accepted by the SQLite schema."""
    return ", ".join(f"'{kind.value}'" for kind in PayloadKind)
