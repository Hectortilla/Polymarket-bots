"""Replay-selection section of a persisted performance summary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from polybot.backtesting.contracts import BacktestGapPolicy
from polybot.recording.contracts.session import SessionIntegrityStatus

from ..files import PerformanceSelectionField
from ..parsing import nonnegative_int, required_bool, require_exact_keys
from ..run import RunSelection


@dataclass(frozen=True, slots=True)
class PerformanceSelectionSummary:
    """Validated archive interval, market, and coverage-gap selection."""

    session_id: int | None
    start_ms: int
    end_ms: int | None
    market_slugs: tuple[str, ...]
    replay_cutoff_sequence: int | None
    session_integrity_status: SessionIntegrityStatus | None
    uses_partial_session: bool
    gap_policy: BacktestGapPolicy | None
    coverage_gap_ids: tuple[int, ...]
    coverage_gap_duration_ms: int
    coverage_gap_open_count: int
    coverage_gap_affected_position_token_ids: tuple[str, ...]

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> PerformanceSelectionSummary:
        """Decode selection and reuse the shared run-selection invariants."""
        require_exact_keys(payload, PerformanceSelectionField, "selection")
        session_integrity_status = _optional_enum(
            payload,
            PerformanceSelectionField.SESSION_INTEGRITY_STATUS,
            SessionIntegrityStatus,
        )
        gap_policy = _optional_enum(
            payload,
            PerformanceSelectionField.GAP_POLICY,
            BacktestGapPolicy,
        )
        coverage_gap_ids = _positive_int_tuple(
            payload,
            PerformanceSelectionField.COVERAGE_GAP_IDS,
        )
        coverage_gap_count = nonnegative_int(
            payload,
            PerformanceSelectionField.COVERAGE_GAP_COUNT,
        )
        if coverage_gap_count != len(coverage_gap_ids):
            raise ValueError("performance summary coverage gap count is inconsistent")
        affected_position_token_ids = _unique_text_tuple(
            payload,
            PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_TOKEN_IDS,
        )
        affected_position_count = nonnegative_int(
            payload,
            PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_COUNT,
        )
        if affected_position_count != len(affected_position_token_ids):
            raise ValueError(
                "performance summary affected position count is inconsistent"
            )
        try:
            selection = RunSelection(
                session_id=_optional_positive_int(
                    payload,
                    PerformanceSelectionField.SESSION_ID,
                ),
                start_ms=nonnegative_int(payload, PerformanceSelectionField.START_MS),
                end_ms=_optional_nonnegative_int(
                    payload,
                    PerformanceSelectionField.END_MS,
                ),
                market_slugs=_unique_text_tuple(
                    payload,
                    PerformanceSelectionField.MARKET_SLUGS,
                ),
                replay_cutoff_sequence=_optional_positive_int(
                    payload,
                    PerformanceSelectionField.REPLAY_CUTOFF_SEQUENCE,
                ),
                session_integrity_status=session_integrity_status,
                uses_partial_session=required_bool(
                    payload,
                    PerformanceSelectionField.USES_PARTIAL_SESSION,
                ),
                gap_policy=gap_policy,
                coverage_gap_ids=coverage_gap_ids,
                coverage_gap_duration_ms=nonnegative_int(
                    payload,
                    PerformanceSelectionField.COVERAGE_GAP_DURATION_MS,
                ),
                coverage_gap_open_count=nonnegative_int(
                    payload,
                    PerformanceSelectionField.COVERAGE_GAP_OPEN_COUNT,
                ),
            )
        except ValueError as error:
            raise ValueError("performance summary selection is invalid") from error
        return cls(
            session_id=selection.session_id,
            start_ms=selection.start_ms,
            end_ms=selection.end_ms,
            market_slugs=selection.market_slugs,
            replay_cutoff_sequence=selection.replay_cutoff_sequence,
            session_integrity_status=selection.session_integrity_status,
            uses_partial_session=selection.uses_partial_session,
            gap_policy=selection.gap_policy,
            coverage_gap_ids=selection.coverage_gap_ids,
            coverage_gap_duration_ms=selection.coverage_gap_duration_ms,
            coverage_gap_open_count=selection.coverage_gap_open_count,
            coverage_gap_affected_position_token_ids=affected_position_token_ids,
        )

    def to_dict(self) -> dict[str, object]:
        """Encode the stable selection section."""
        return {
            PerformanceSelectionField.SESSION_ID: self.session_id,
            PerformanceSelectionField.START_MS: self.start_ms,
            PerformanceSelectionField.END_MS: self.end_ms,
            PerformanceSelectionField.MARKET_SLUGS: list(self.market_slugs),
            PerformanceSelectionField.REPLAY_CUTOFF_SEQUENCE: (
                self.replay_cutoff_sequence
            ),
            PerformanceSelectionField.SESSION_INTEGRITY_STATUS: (
                None
                if self.session_integrity_status is None
                else self.session_integrity_status.value
            ),
            PerformanceSelectionField.USES_PARTIAL_SESSION: (
                self.uses_partial_session
            ),
            PerformanceSelectionField.GAP_POLICY: (
                None if self.gap_policy is None else self.gap_policy.value
            ),
            PerformanceSelectionField.COVERAGE_GAP_IDS: list(self.coverage_gap_ids),
            PerformanceSelectionField.COVERAGE_GAP_COUNT: len(self.coverage_gap_ids),
            PerformanceSelectionField.COVERAGE_GAP_DURATION_MS: (
                self.coverage_gap_duration_ms
            ),
            PerformanceSelectionField.COVERAGE_GAP_OPEN_COUNT: (
                self.coverage_gap_open_count
            ),
            PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_TOKEN_IDS: list(
                self.coverage_gap_affected_position_token_ids
            ),
            PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_COUNT: len(
                self.coverage_gap_affected_position_token_ids
            ),
        }


def _optional_positive_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"performance summary {key} must be positive or null")
    return value


def _optional_nonnegative_int(
    payload: Mapping[str, object],
    key: str,
) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"performance summary {key} must be nonnegative or null")
    return value


def _optional_enum(
    payload: Mapping[str, object],
    key: str,
    enum_type: type[SessionIntegrityStatus] | type[BacktestGapPolicy],
) -> SessionIntegrityStatus | BacktestGapPolicy | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"performance summary {key} must be text or null")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"performance summary {key} is invalid") from error


def _positive_int_tuple(payload: Mapping[str, object], key: str) -> tuple[int, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0
        for item in value
    ):
        raise ValueError(f"performance summary {key} must be positive integer values")
    normalized = tuple(value)
    if normalized != tuple(sorted(set(normalized))):
        raise ValueError(f"performance summary {key} must be sorted and unique")
    return normalized


def _unique_text_tuple(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"performance summary {key} must be an array")
    normalized = tuple(
        item.strip() if isinstance(item, str) else "" for item in value
    )
    if not all(normalized) or len(normalized) != len(set(normalized)):
        raise ValueError(f"performance summary {key} must contain unique text")
    if key is PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_TOKEN_IDS and (
        normalized != tuple(sorted(normalized))
    ):
        raise ValueError(f"performance summary {key} must be sorted")
    return normalized
