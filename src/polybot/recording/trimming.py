"""Safe replacement of a recording with its largest replayable interval."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from polybot.persistence.fsync import fsync_path

from .archive.reader import RecordingReader
from .trim_contracts import (
    DEFAULT_TRIM_BACKUP_SUFFIX,
    RecordingTrimError,
    RecordingTrimPlan,
    RecordingTrimResult,
)
from .trim_export import build_trimmed_archive
from .trim_files import (
    remove_archive_artifacts,
    remove_sqlite_sidecars,
    temporary_archive_path,
)
from .trim_planning import plan_recording_trim
from .trim_validation import validate_trimmed_archive


class _TrimStage(StrEnum):
    RESOLVE_SOURCE = "resolving the source archive path"
    OPEN_SOURCE = "opening the source archive"
    SELECT_INTERVAL = "selecting the retained interval"
    REPORT_INTERVAL = "reporting the retained interval"
    CHECK_BACKUP = "checking the backup path"
    CREATE_TEMPORARY = "creating the temporary archive"
    EXPORT = "exporting the retained interval"
    VALIDATE = "validating the temporary archive"
    PRESERVE_PERMISSIONS = "preserving source permissions"
    SYNC_TEMPORARY = "synchronizing the temporary archive"
    CREATE_BACKUP = "creating the backup"
    SYNC_BACKUP = "synchronizing the backup"
    REMOVE_SIDECARS = "removing stale SQLite sidecars"
    INSTALL = "installing the replacement"
    SYNC_REPLACEMENT = "synchronizing the replacement"
    READ_SIZE = "reading the replacement size"


def trim_recording(
    path: str | Path,
    *,
    session_id: int | None = None,
    dry_run: bool = False,
    keep_backup: bool = True,
    on_plan: Callable[[RecordingTrimPlan], None] | None = None,
) -> RecordingTrimResult:
    """Plan and optionally atomically install the largest replayable interval."""

    archive_path = Path(path)
    reader: RecordingReader | None = None
    temporary_path: Path | None = None
    backup_path: Path | None = None
    backup_created = False
    replacement_installed = False
    result: RecordingTrimResult | None = None
    failure: BaseException | None = None
    stage = _TrimStage.RESOLVE_SOURCE
    try:
        archive_path = archive_path.expanduser().resolve()
        stage = _TrimStage.OPEN_SOURCE
        reader = RecordingReader.for_replay(archive_path)
        stage = _TrimStage.SELECT_INTERVAL
        plan = plan_recording_trim(
            reader,
            archive_path=archive_path,
            session_id=session_id,
        )
        if on_plan is not None:
            stage = _TrimStage.REPORT_INTERVAL
            on_plan(plan)
        if dry_run:
            result = RecordingTrimResult(plan=plan, replaced=False)
        else:
            stage = _TrimStage.CHECK_BACKUP
            if keep_backup:
                backup_path = archive_path.with_name(
                    f"{archive_path.name}{DEFAULT_TRIM_BACKUP_SUFFIX}"
                )
                if backup_path.exists():
                    raise RecordingTrimError(
                        f"trim backup already exists: {backup_path}"
                    )

            stage = _TrimStage.CREATE_TEMPORARY
            temporary_path = temporary_archive_path(archive_path)
            stage = _TrimStage.EXPORT
            synthetic_event_count = build_trimmed_archive(
                reader,
                plan,
                temporary_path,
            )
            stage = _TrimStage.VALIDATE
            validate_trimmed_archive(
                temporary_path,
                plan,
                expected_event_count=(
                    plan.source_event_count + synthetic_event_count
                ),
            )
            stage = _TrimStage.PRESERVE_PERMISSIONS
            os.chmod(
                temporary_path,
                stat.S_IMODE(archive_path.stat().st_mode),
            )
            stage = _TrimStage.SYNC_TEMPORARY
            fsync_path(temporary_path)

            if backup_path is not None:
                stage = _TrimStage.CREATE_BACKUP
                os.link(archive_path, backup_path)
                backup_created = True
                stage = _TrimStage.SYNC_BACKUP
                fsync_path(archive_path.parent)

            stage = _TrimStage.REMOVE_SIDECARS
            remove_sqlite_sidecars(archive_path)
            stage = _TrimStage.INSTALL
            os.replace(temporary_path, archive_path)
            replacement_installed = True
            stage = _TrimStage.SYNC_REPLACEMENT
            fsync_path(archive_path.parent)
            stage = _TrimStage.READ_SIZE
            result = RecordingTrimResult(
                plan=plan,
                replaced=True,
                backup_path=backup_path,
                trimmed_size_bytes=archive_path.stat().st_size,
                synthetic_event_count=synthetic_event_count,
            )
    except BaseException as error:
        failure = error

    cleanup_failures, backup_retained = _cleanup_trim_resources(
        reader=reader,
        temporary_path=temporary_path,
        backup_path=backup_path,
        backup_created=backup_created,
        remove_backup=backup_created and not replacement_installed,
    )
    if failure is not None:
        if isinstance(failure, OSError):
            raise RecordingTrimError(
                _failure_message(
                    replacement_installed=replacement_installed,
                    detail=f"filesystem failure while {stage}: {failure}",
                    backup_path=backup_path if backup_retained else None,
                    cleanup_failures=cleanup_failures,
                )
            ) from failure
        if (
            isinstance(failure, RuntimeError)
            and stage is _TrimStage.RESOLVE_SOURCE
        ):
            raise RecordingTrimError(
                _failure_message(
                    replacement_installed=False,
                    detail=f"path normalization failed: {failure}",
                    backup_path=None,
                    cleanup_failures=cleanup_failures,
                )
            ) from failure
        if cleanup_failures:
            if isinstance(failure, Exception):
                raise RecordingTrimError(
                    _failure_message(
                        replacement_installed=replacement_installed,
                        detail=str(failure),
                        backup_path=backup_path if backup_retained else None,
                        cleanup_failures=cleanup_failures,
                    )
                ) from failure
            failure.add_note(_cleanup_failure_detail(cleanup_failures))
        raise failure
    if cleanup_failures:
        raise RecordingTrimError(
            _failure_message(
                replacement_installed=replacement_installed,
                detail="trim operation completed but cleanup failed",
                backup_path=backup_path if backup_retained else None,
                cleanup_failures=cleanup_failures,
            )
        )
    if result is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("recording trim did not produce a result")
    return result


def _cleanup_trim_resources(
    *,
    reader: RecordingReader | None,
    temporary_path: Path | None,
    backup_path: Path | None,
    backup_created: bool,
    remove_backup: bool,
) -> tuple[tuple[tuple[str, Exception], ...], bool]:
    failures: list[tuple[str, Exception]] = []
    backup_retained = backup_created
    if remove_backup and backup_path is not None:
        try:
            backup_path.unlink(missing_ok=True)
            backup_retained = False
        except Exception as error:
            failures.append(("removing the temporary backup", error))
            backup_retained = True
    if reader is not None:
        try:
            reader.close()
        except Exception as error:
            failures.append(("closing the source archive", error))
    if temporary_path is not None:
        try:
            remove_archive_artifacts(temporary_path)
        except Exception as error:
            failures.append(("removing temporary archive files", error))
    return tuple(failures), backup_retained


def _failure_message(
    *,
    replacement_installed: bool,
    detail: str,
    backup_path: Path | None,
    cleanup_failures: tuple[tuple[str, Exception], ...],
) -> str:
    status = "was replaced" if replacement_installed else "was not replaced"
    message = f"recording {status}; {detail}"
    if backup_path is not None:
        message += f"; backup retained at {backup_path}"
    if cleanup_failures:
        message += f"; {_cleanup_failure_detail(cleanup_failures)}"
    return message


def _cleanup_failure_detail(
    failures: tuple[tuple[str, Exception], ...],
) -> str:
    return "cleanup failure while " + "; while ".join(
        f"{action}: {error}" for action, error in failures
    )
