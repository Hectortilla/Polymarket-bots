"""Internal state and control messages for recording coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field

from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.recording_feed.capture import MarketCapture
from polybot.polymarket.recording_metadata.contracts import RecordingMarket
from polybot.recording.contracts.gaps import CoverageGapReason


@dataclass(slots=True)
class TrackedMarket:
    """Mutable capture state for one immutable market condition."""

    recording: RecordingMarket
    generation: int = 0
    capture: MarketCapture | None = None
    projector: BookDepthProjector | None = None
    pump: asyncio.Task[None] | None = None
    dropped_count: int = 0
    last_observed_at_ms: int = 0
    gap_ids: set[int] = field(default_factory=set)
    coverage_started: bool = False
    terminal_claimed: bool = False

    @property
    def condition_id(self) -> str:
        return self.recording.market.condition_id


@dataclass(frozen=True, slots=True)
class CaptureStopped:
    """Signal that one capture stream needs recovery or failure handling."""

    condition_id: str
    generation: int
    reason: CoverageGapReason
    error: BaseException | None = None
    fatal: bool = False


@dataclass(frozen=True, slots=True)
class ResolutionStored:
    """Signal that a streamed resolution is durably committed."""

    condition_id: str
    generation: int


type ControlMessage = CaptureStopped | ResolutionStored


@dataclass(frozen=True, slots=True)
class ReleasedResumedGap:
    """A resumed gap whose last affected condition has recovered."""

    gap_id: int
    condition_id: str
    affected_condition_ids: frozenset[str]


class ResumedGapRecovery:
    """Track multi-condition recovery before closing resumed coverage gaps."""

    def __init__(
        self,
        conditions_by_gap_id: Mapping[int, frozenset[str]] | None,
    ) -> None:
        conditions = {} if conditions_by_gap_id is None else conditions_by_gap_id
        self._remaining_conditions_by_gap_id = {
            gap_id: set(condition_ids)
            for gap_id, condition_ids in conditions.items()
        }
        self._affected_conditions_by_gap_id = {
            gap_id: frozenset(condition_ids)
            for gap_id, condition_ids in conditions.items()
        }

    def needs_recovery(
        self,
        condition_id: str,
        own_gap_ids: set[int],
    ) -> bool:
        return bool(own_gap_ids) or any(
            condition_id in remaining
            for remaining in self._remaining_conditions_by_gap_id.values()
        )

    def remaining_condition_ids(self, gap_id: int) -> frozenset[str]:
        """Return the conditions still required before one resumed gap closes."""
        return frozenset(
            self._remaining_conditions_by_gap_id.get(gap_id, ())
        )

    def is_in_open_scope(
        self,
        condition_id: str,
        own_gap_ids: set[int],
    ) -> bool:
        return bool(own_gap_ids) or any(
            condition_id in self._affected_conditions_by_gap_id[gap_id]
            for gap_id in self._remaining_conditions_by_gap_id
        )

    def release_condition(
        self,
        condition_id: str,
    ) -> tuple[ReleasedResumedGap, ...]:
        """Mark one condition recovered and report gaps now ready to close."""
        released: list[ReleasedResumedGap] = []
        for gap_id, remaining in self._remaining_conditions_by_gap_id.items():
            if condition_id not in remaining:
                continue
            remaining.remove(condition_id)
            if remaining:
                continue
            released.append(
                ReleasedResumedGap(
                    gap_id=gap_id,
                    condition_id=condition_id,
                    affected_condition_ids=self._affected_conditions_by_gap_id[
                        gap_id
                    ],
                )
            )
        return tuple(released)

    def restore_release(self, released: ReleasedResumedGap) -> None:
        """Undo a failed archive close so the gap remains recoverable."""
        self._remaining_conditions_by_gap_id[released.gap_id].add(
            released.condition_id
        )

    def close_released_gap(self, released: ReleasedResumedGap) -> None:
        """Forget a successfully closed resumed gap."""
        self._remaining_conditions_by_gap_id.pop(released.gap_id, None)
        self._affected_conditions_by_gap_id.pop(released.gap_id, None)
