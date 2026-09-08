"""Typed rows and selections returned by recording archives."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from polybot.framework.timestamps import require_nonnegative_timestamp
from polybot.integers import validate_nonnegative_int, validate_positive_int

from ..contracts.kinds import PayloadKind
from ..contracts.session import SessionIntegrityStatus, SessionState


@dataclass(frozen=True, slots=True)
class RecordingSession:
    session_id: int
    started_at_ms: int
    ended_at_ms: int | None
    clean_close: bool
    integrity_status: SessionIntegrityStatus
    recorder_version: str
    sdk_version: str
    failure_reason: str | None

    def __post_init__(self) -> None:
        validate_positive_int(self.session_id, "recording session ID")
        require_nonnegative_timestamp(self.started_at_ms, "recording session start")
        if self.ended_at_ms is not None:
            require_nonnegative_timestamp(self.ended_at_ms, "recording session end")
        if self.ended_at_ms is not None and self.ended_at_ms < self.started_at_ms:
            raise ValueError("recording session ends before it starts")
        if not self.recorder_version or not self.sdk_version:
            raise ValueError("recording session version provenance is incomplete")
        SessionState(
            self.ended_at_ms,
            self.clean_close,
            self.integrity_status,
            self.failure_reason,
        )


@dataclass(frozen=True, slots=True)
class RecordingEventBounds:
    """First and last event coordinates for one immutable reader selection."""

    first_sequence: int
    last_sequence: int
    start_at_ms: int
    end_at_ms: int


@dataclass(frozen=True, slots=True)
class RecordingFeatureProvenance:
    feature_name: str
    available_from_session_id: int
    enabled_at_ms: int
    recorder_version: str


@dataclass(frozen=True, slots=True)
class RecordingEventCounts:
    market_metadata: int = 0
    book_baseline: int = 0
    book_delta: int = 0
    public_trade: int = 0
    tick_size_change: int = 0
    resolution: int = 0
    coverage_gap: int = 0

    def __post_init__(self) -> None:
        for value in self.as_tuple():
            validate_nonnegative_int(value, "recording event count")

    @property
    def replay_event_count(self) -> int:
        return sum(
            getattr(self, kind.event_count_field)
            for kind in PayloadKind
            if kind.is_replay_event
        )

    @property
    def stored_event_count(self) -> int:
        return sum(self.as_tuple())

    def as_tuple(self) -> tuple[int, ...]:
        return tuple(getattr(self, kind.event_count_field) for kind in PayloadKind)

    @classmethod
    def combine(
        cls,
        counts: Iterable[RecordingEventCounts],
    ) -> RecordingEventCounts:
        values = tuple(counts)
        totals = {
            kind.event_count_field: sum(
                getattr(value, kind.event_count_field) for value in values
            )
            for kind in PayloadKind
        }
        return cls(**totals)


@dataclass(frozen=True, slots=True)
class RecordingMarketStatistics:
    condition_id: str
    market_slug: str
    event_count: int
    start_at_ms: int
    end_at_ms: int

    def __post_init__(self) -> None:
        if not self.condition_id or not self.market_slug:
            raise ValueError("recording market statistics require market identity")
        if self.event_count <= 0:
            raise ValueError("recording market statistics require events")
        if self.start_at_ms < 0 or self.end_at_ms < self.start_at_ms:
            raise ValueError("recording market statistics have invalid bounds")

    @property
    def duration_ms(self) -> int:
        return self.end_at_ms - self.start_at_ms


@dataclass(frozen=True, slots=True)
class RecordingSessionStatistics:
    session: RecordingSession
    event_bounds: RecordingEventBounds | None
    event_counts: RecordingEventCounts
    checkpoint_count: int
    capture_anomaly_count: int | None
    markets: tuple[RecordingMarketStatistics, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.session, RecordingSession):
            raise ValueError("recording session statistics require a session")
        if not isinstance(self.event_counts, RecordingEventCounts):
            raise ValueError("recording session statistics require event counts")
        validate_nonnegative_int(self.checkpoint_count, "recording checkpoint count")
        if self.capture_anomaly_count is not None:
            validate_nonnegative_int(
                self.capture_anomaly_count, "recording anomaly count"
            )
        if (self.event_bounds is None) != (self.event_counts.replay_event_count == 0):
            raise ValueError("recording event bounds disagree with event counts")
        if not isinstance(self.markets, tuple) or not all(
            isinstance(market, RecordingMarketStatistics) for market in self.markets
        ):
            raise ValueError("recording session markets are invalid")
        identities = tuple(
            (market.condition_id, market.market_slug) for market in self.markets
        )
        if len(identities) != len(set(identities)):
            raise ValueError("recording session statistics contain duplicate markets")

    @property
    def duration_ms(self) -> int:
        if self.event_bounds is None:
            return 0
        return self.event_bounds.end_at_ms - self.event_bounds.start_at_ms
