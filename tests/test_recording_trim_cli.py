from __future__ import annotations

from pathlib import Path

import pytest

from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.recording import trim as trim_cli
from polybot.recording.archive_errors import ArchiveFormatError
from polybot.recording.archive_models import RecordingSession
from polybot.recording.contracts import SessionIntegrityStatus
from polybot.recording.trim_contracts import (
    RecordingTrimError,
    RecordingTrimPlan,
    RecordingTrimResult,
)


def _plan(tmp_path: Path) -> RecordingTrimPlan:
    return RecordingTrimPlan(
        archive_path=(tmp_path / "capture.sqlite3").resolve(),
        target_identity="slugs:alpha",
        source_session=RecordingSession(
            session_id=7,
            started_at_ms=100,
            ended_at_ms=900,
            clean_close=True,
            integrity_status=SessionIntegrityStatus.INCOMPLETE,
            recorder_version="test-recorder",
            sdk_version="test-sdk",
            failure_reason=None,
        ),
        start_at_ms=250,
        end_at_ms=800,
        market_slugs=("alpha",),
        source_event_count=321,
        source_gap_count=4,
        source_size_bytes=12_345,
    )


def test_argument_parser_accepts_supported_options() -> None:
    parser = trim_cli._argument_parser()

    defaults = parser.parse_args(("capture.sqlite3",))
    configured = parser.parse_args(
        (
            "capture.sqlite3",
            "--session",
            "7",
            "--dry-run",
            "--no-backup",
        )
    )

    assert defaults.archive == Path("capture.sqlite3")
    assert defaults.session is None
    assert defaults.dry_run is False
    assert defaults.no_backup is False
    assert configured.session == 7
    assert configured.dry_run is True
    assert configured.no_backup is True

    with pytest.raises(SystemExit):
        parser.parse_args(())
    with pytest.raises(SystemExit):
        parser.parse_args(("capture.sqlite3", "--session", "0"))


def test_main_forwards_dry_run_and_prints_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _plan(tmp_path)
    captured: dict[str, object] = {}

    def fake_trim_recording(path: Path, **kwargs: object) -> RecordingTrimResult:
        captured["path"] = path
        captured.update(kwargs)
        callback = kwargs["on_plan"]
        assert callable(callback)
        callback(plan)
        return RecordingTrimResult(plan=plan, replaced=False)

    monkeypatch.setattr(trim_cli, "trim_recording", fake_trim_recording)

    result = trim_cli.main(
        [
            str(plan.archive_path),
            "--session",
            "7",
            "--dry-run",
            "--no-backup",
        ]
    )

    assert result == 0
    assert captured == {
        "path": plan.archive_path,
        "session_id": 7,
        "dry_run": True,
        "keep_backup": False,
        "on_plan": trim_cli._print_plan,
    }
    output = capsys.readouterr().out
    assert "Trim plan" in output
    assert "Clean interval" in output
    assert "250 → 800" in output
    assert "0.550s" in output
    assert "321" in output
    assert "12.06 KiB" in output
    assert "Dry run complete" in output
    assert "Archive unchanged" in output
    assert plan.archive_path.name in output


@pytest.mark.parametrize("keep_backup", (True, False))
def test_main_prints_replacement_backup_and_trimmed_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    keep_backup: bool,
) -> None:
    plan = _plan(tmp_path)
    backup_path = (
        plan.archive_path.with_name(f"{plan.archive_path.name}.pre-trim")
        if keep_backup
        else None
    )

    def fake_trim_recording(path: Path, **kwargs: object) -> RecordingTrimResult:
        assert kwargs["keep_backup"] is keep_backup
        callback = kwargs["on_plan"]
        assert callable(callback)
        callback(plan)
        return RecordingTrimResult(
            plan=plan,
            replaced=True,
            backup_path=backup_path,
            trimmed_size_bytes=6_789,
            synthetic_event_count=3,
        )

    monkeypatch.setattr(trim_cli, "trim_recording", fake_trim_recording)
    arguments = [str(plan.archive_path)]
    if not keep_backup:
        arguments.append("--no-backup")

    assert trim_cli.main(arguments) == 0

    output = capsys.readouterr().out
    assert "Recording trim complete" in output
    assert plan.archive_path.name in output
    assert "Trimmed size" in output
    assert "6.63 KiB" in output
    if backup_path is None:
        assert "Not retained (--no-backup)" in output
    else:
        assert "Backup" in output
        assert backup_path.name in output
        assert "Not retained" not in output


@pytest.mark.parametrize(
    "error",
    (
        RecordingTrimError("no replayable interval"),
        ArchiveFormatError("unsupported recording"),
        BacktestError(
            BacktestFailureReason.INVALID_SELECTION,
            "invalid replay selection",
        ),
    ),
)
def test_main_reports_domain_errors_through_argument_parser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    def fail_trim_recording(path: Path, **kwargs: object) -> RecordingTrimResult:
        raise error

    monkeypatch.setattr(trim_cli, "trim_recording", fail_trim_recording)

    with pytest.raises(SystemExit, match="2"):
        trim_cli.main(["capture.sqlite3"])

    assert str(error) in capsys.readouterr().err


def test_main_reports_filesystem_errors_through_argument_parser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = RecordingTrimError(
        "recording was not replaced; filesystem failure while creating the backup"
    )

    def fail_trim_recording(path: Path, **kwargs: object) -> RecordingTrimResult:
        raise error

    monkeypatch.setattr(trim_cli, "trim_recording", fail_trim_recording)

    with pytest.raises(SystemExit, match="2"):
        trim_cli.main(["capture.sqlite3"])

    assert str(error) in capsys.readouterr().err
