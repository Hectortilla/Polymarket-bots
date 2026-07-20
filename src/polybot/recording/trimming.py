"""Safe replacement of a recording with its largest replayable interval."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

from .archive import RecordingReader
from .trim_contracts import (
    DEFAULT_TRIM_BACKUP_SUFFIX,
    RecordingTrimError,
    RecordingTrimPlan,
    RecordingTrimResult,
)
from .trim_export import (
    build_trimmed_archive,
    fsync_directory,
    fsync_file,
    remove_archive_artifacts,
    remove_sqlite_sidecars,
    temporary_archive_path,
)
from .trim_planning import plan_recording_trim
from .trim_validation import validate_trimmed_archive


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
    stage = "resolving the source archive path"
    try:
        archive_path = archive_path.expanduser().resolve()
        stage = "opening the source archive"
        reader = RecordingReader.for_replay(archive_path)
        stage = "selecting the retained interval"
        plan = plan_recording_trim(
            reader,
            archive_path=archive_path,
            session_id=session_id,
        )
        if on_plan is not None:
            stage = "reporting the retained interval"
            on_plan(plan)
        if dry_run:
            result = RecordingTrimResult(plan=plan, replaced=False)
        else:
            stage = "checking the backup path"
            if keep_backup:
                backup_path = archive_path.with_name(
                    f"{archive_path.name}{DEFAULT_TRIM_BACKUP_SUFFIX}"
                )
                if backup_path.exists():
                    raise RecordingTrimError(
                        f"trim backup already exists: {backup_path}"
                    )

            stage = "creating the temporary archive"
            temporary_path = temporary_archive_path(archive_path)
            stage = "exporting the retained interval"
            synthetic_event_count = build_trimmed_archive(
                reader,
                plan,
                temporary_path,
            )
            stage = "validating the temporary archive"
            validate_trimmed_archive(
                temporary_path,
                plan,
                expected_event_count=(
                    plan.source_event_count + synthetic_event_count
                ),
            )
            stage = "preserving source permissions"
            os.chmod(
                temporary_path,
                stat.S_IMODE(archive_path.stat().st_mode),
            )
            stage = "synchronizing the temporary archive"
            fsync_file(temporary_path)

            if backup_path is not None:
                stage = "creating the backup"
                os.link(archive_path, backup_path)
                backup_created = True
                stage = "synchronizing the backup"
                fsync_directory(archive_path.parent)

            stage = "removing stale SQLite sidecars"
            remove_sqlite_sidecars(archive_path)
            stage = "installing the replacement"
            os.replace(temporary_path, archive_path)
            replacement_installed = True
            stage = "synchronizing the replacement"
            fsync_directory(archive_path.parent)
            stage = "reading the replacement size"
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
            and stage == "resolving the source archive path"
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
