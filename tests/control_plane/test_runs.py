from datetime import UTC

from polybot_control_plane.runs.contracts import RunRead, RunStatus
from polybot_control_plane.runs.models import RunRow


def test_run_contract_matches_the_run_row() -> None:
    row_fields = tuple(RunRow.__table__.columns.keys())
    assert tuple(RunRead.model_fields)[: len(row_fields)] == row_fields
    assert tuple(RunRead.model_fields)[len(row_fields) :] == (
        "latest_equity",
        "equity_status",
    )
    assert len(row_fields) == 9
    assert "latest_equity" not in RunRow.__table__.columns
    assert "equity_status" not in RunRow.__table__.columns
    assert RunRow.__table__.columns.status.type.enums == [
        status.value for status in RunStatus
    ]


def test_run_row_defaults_are_public_contract_values() -> None:
    row = RunRow(
        definition_id="definition",
        config={},
    )

    assert row.status is RunStatus.QUEUED
    assert row.created_at.tzinfo is UTC
