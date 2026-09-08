from polybot.framework.cadence import (
    advance_deadline_past,
    next_interval_boundary_ms,
)


def test_advance_deadline_past_preserves_or_advances_the_deadline() -> None:
    assert advance_deadline_past(16.0, 2.0, 15.0) == 16.0
    assert advance_deadline_past(10.0, 2.0, 15.0) == 16.0


def test_next_interval_boundary_ms_returns_the_next_strict_boundary() -> None:
    assert next_interval_boundary_ms(2_000, 1_000) == 3_000
    assert next_interval_boundary_ms(2_500, 1_000) == 3_000
