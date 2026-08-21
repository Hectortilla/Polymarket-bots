from datetime import UTC

from polybot_control_plane.catalog.definitions import INITIAL_DEFINITION_VERSION
from polybot_control_plane.runs.contracts import RunRead, RunStatus
from polybot_control_plane.runs.models import RunRow


def test_run_contract_matches_the_slice_12a_row() -> None:
    assert tuple(RunRead.model_fields) == tuple(RunRow.__table__.columns.keys())
    assert len(RunRead.model_fields) == 6
    assert RunRow.__table__.columns.status.type.enums == [
        status.value for status in RunStatus
    ]


def test_run_row_defaults_are_public_contract_values() -> None:
    row = RunRow(
        definition_id="definition",
        definition_version=INITIAL_DEFINITION_VERSION,
        config={},
    )

    assert row.status is RunStatus.QUEUED
    assert row.created_at.tzinfo is UTC
