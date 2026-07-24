"""Filesystem helpers for publishing and cleaning recording trims."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path

from .archive.paths import (
    ARCHIVE_ARTIFACT_SUFFIXES,
    RECORDING_ARCHIVE_SUFFIX,
    SQLITE_SIDECAR_SUFFIXES,
)


def temporary_archive_path(archive_path: Path) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{archive_path.name}.trim-",
        suffix=RECORDING_ARCHIVE_SUFFIX,
        dir=archive_path.parent,
    )
    os.close(descriptor)
    path = Path(raw_path)
    path.unlink()
    return path


def remove_sqlite_sidecars(path: Path) -> None:
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        with suppress(FileNotFoundError):
            path.with_name(f"{path.name}{suffix}").unlink()


def remove_archive_artifacts(path: Path) -> None:
    for suffix in ARCHIVE_ARTIFACT_SUFFIXES:
        candidate = path if not suffix else path.with_name(f"{path.name}{suffix}")
        with suppress(FileNotFoundError):
            candidate.unlink()
