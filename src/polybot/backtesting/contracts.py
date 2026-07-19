"""Stable contracts for deterministic archive replay."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from polybot.recording.contracts import SessionIntegrityStatus


class BacktestFailureReason(StrEnum):
    UNSUPPORTED_ARCHIVE = "unsupported_archive"
    SESSION_NOT_REPLAYABLE = "session_not_replayable"
    INVALID_SELECTION = "invalid_selection"
    COVERAGE_GAP = "coverage_gap"
    MISSING_MARKET_DATA = "missing_market_data"
    UNSUPPORTED_INPUT = "unsupported_input"
    EMPTY_SELECTION = "empty_selection"


class BacktestError(RuntimeError):
    def __init__(self, reason: BacktestFailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class BacktestOptions:
    archive_path: Path
    session_id: int | None = None
    start_at_ms: int | None = None
    end_at_ms: int | None = None
    market_slugs: tuple[str, ...] = ()
    seed: int = 0
    results_dir: Path | None = None
    report_interval_ms: int = 1_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "archive_path", Path(self.archive_path))
        if self.results_dir is not None:
            object.__setattr__(self, "results_dir", Path(self.results_dir))
        if self.session_id is not None and (
            isinstance(self.session_id, bool)
            or not isinstance(self.session_id, int)
            or self.session_id <= 0
        ):
            raise ValueError("backtest session ID must be positive")
        if self.start_at_ms is not None and (
            isinstance(self.start_at_ms, bool)
            or not isinstance(self.start_at_ms, int)
            or self.start_at_ms < 0
        ):
            raise ValueError("backtest start must be nonnegative")
        if self.end_at_ms is not None and (
            isinstance(self.end_at_ms, bool)
            or not isinstance(self.end_at_ms, int)
            or self.end_at_ms < 0
        ):
            raise ValueError("backtest end must be nonnegative")
        if (
            self.start_at_ms is not None
            and self.end_at_ms is not None
            and self.end_at_ms < self.start_at_ms
        ):
            raise ValueError("backtest end cannot precede its start")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("backtest seed must be an integer")
        if (
            isinstance(self.report_interval_ms, bool)
            or not isinstance(self.report_interval_ms, int)
            or self.report_interval_ms <= 0
        ):
            raise ValueError("report interval must be positive")
        if any(
            not isinstance(slug, str) or not slug.strip()
            for slug in self.market_slugs
        ):
            raise ValueError("backtest market slugs must not be empty")
        normalized_slugs = tuple(
            dict.fromkeys(slug.strip() for slug in self.market_slugs)
        )
        object.__setattr__(self, "market_slugs", normalized_slugs)


@dataclass(frozen=True, slots=True)
class BacktestSelection:
    session_id: int
    start_at_ms: int
    end_at_ms: int
    market_slugs: tuple[str, ...]
    replay_cutoff_sequence: int
    session_integrity_status: SessionIntegrityStatus = (
        SessionIntegrityStatus.COMPLETE
    )
    uses_partial_session: bool = False


@dataclass(frozen=True, slots=True)
class BacktestResult:
    selection: BacktestSelection
    results_dir: Path
    event_count: int
    accepted_dispatch_count: int
    skipped_dispatch_count: int
    resolution_count: int
