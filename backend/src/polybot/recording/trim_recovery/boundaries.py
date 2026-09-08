from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecoveryTokenBoundary:
    token_id: str
    start_at_ms: int
    after_sequence: int


def recovery_sequence_cutoffs(
    boundaries: tuple[RecoveryTokenBoundary, ...] | None,
) -> dict[str, int] | None:
    """Convert recovery boundaries into strict per-token sequence floors."""

    if boundaries is None:
        return None
    return {boundary.token_id: boundary.after_sequence for boundary in boundaries}
