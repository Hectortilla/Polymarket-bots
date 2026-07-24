"""Physical SQLite format validation for recording archives."""

from __future__ import annotations

import sqlite3

from .errors import ArchiveFormatError
from .primitives import _required_text
from .schema import (
    CORE_ARCHIVE_TABLE_COLUMNS,
    SCHEMA_VERSION,
    SQLITE_APPLICATION_ID,
)


def _validate_archive(connection: sqlite3.Connection) -> str:
    try:
        application_id = int(
            connection.execute("PRAGMA application_id").fetchone()[0]
        )
        schema_version = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )
        if application_id != SQLITE_APPLICATION_ID or schema_version != SCHEMA_VERSION:
            raise ArchiveFormatError(
                f"unsupported recording archive schema version {schema_version}"
            )
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ArchiveFormatError("recording archive failed SQLite integrity check")
        _validate_core_schema(connection)
        row = connection.execute(
            """
            SELECT schema_version, target_identity
            FROM archive_meta
            WHERE singleton = 1
            """
        ).fetchone()
        if row is None or row["schema_version"] != SCHEMA_VERSION:
            raise ArchiveFormatError("recording archive metadata is malformed")
        return _required_text(row["target_identity"], "stored target identity")
    except ArchiveFormatError:
        raise
    except (IndexError, sqlite3.Error, TypeError, ValueError) as error:
        raise ArchiveFormatError("recording archive format is malformed") from error


def _validate_core_schema(connection: sqlite3.Connection) -> None:
    for table_name, required_columns in CORE_ARCHIVE_TABLE_COLUMNS.items():
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = {str(row["name"]) for row in rows}
        if not required_columns <= columns:
            raise ArchiveFormatError(
                f"recording archive core table is malformed: {table_name}"
            )
