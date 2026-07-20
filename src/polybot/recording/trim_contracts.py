"""Stable plans and outcomes for recording-archive trimming."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .archive_models import RecordingSession


DEFAULT_TRIM_BACKUP_SUFFIX = ".pre-trim"


class RecordingTrimError(RuntimeError):
    """The archive could not be reduced to a valid replay artifact."""


@dataclass(frozen=True, slots=True)
class RecordingTrimPlan:
    archive_path: Path
    target_identity: str
    source_session: RecordingSession
    start_at_ms: int
    end_at_ms: int
    market_slugs: tuple[str, ...]
    source_event_count: int
    source_gap_count: int
    source_size_bytes: int

    @property
    def duration_ms(self) -> int:
        return self.end_at_ms - self.start_at_ms


@dataclass(frozen=True, slots=True)
class RecordingTrimResult:
    plan: RecordingTrimPlan
    replaced: bool
    backup_path: Path | None = None
    trimmed_size_bytes: int | None = None
    synthetic_event_count: int | None = None
