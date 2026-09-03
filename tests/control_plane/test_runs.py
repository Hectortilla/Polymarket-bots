from datetime import UTC
from uuid import uuid4

from polybot_control_plane.runs.contracts import RunRead
from polybot_control_plane.runs.status import RunStatus
from polybot_control_plane.runs.models import RunRow


def test_run_contract_matches_the_run_row() -> None:
    row_fields = set(RunRow.__table__.columns.keys())
    assert row_fields.issubset(RunRead.model_fields)
    assert set(RunRead.model_fields) - row_fields == {
        "graph_revision",
        "graph",
        "latest_equity",
        "equity_status",
    }
    assert len(row_fields) == 11
    assert "latest_equity" not in RunRow.__table__.columns
    assert "equity_status" not in RunRow.__table__.columns
    assert RunRow.__table__.columns.status.type.enums == [
        status.value for status in RunStatus
    ]


def test_run_row_defaults_are_public_contract_values() -> None:
    row = RunRow(
        bot_id=uuid4(),
        definition_id="definition",
        config={},
    )

    assert row.status is RunStatus.QUEUED
    assert row.created_at.tzinfo is UTC
