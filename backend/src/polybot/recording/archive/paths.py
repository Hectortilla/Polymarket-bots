"""Filename contracts for SQLite recording archives."""

RECORDING_ARCHIVE_SUFFIX = ".sqlite3"
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm")
RECORDING_LOCK_SUFFIX = ".lock"
ARCHIVE_ARTIFACT_SUFFIXES = (
    "",
    *SQLITE_SIDECAR_SUFFIXES,
    RECORDING_LOCK_SUFFIX,
)
