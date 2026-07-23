"""SQLite connection setup shared by recording writers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from .errors import RecordingArchiveError


def readonly_database_uri(path: Path, *, immutable: bool = False) -> str:
    """Return the SQLite URI used for every read-only archive connection."""

    immutable_parameter = "&immutable=1" if immutable else ""
    return f"file:{quote(str(path))}?mode=ro{immutable_parameter}"


def configure_writer_connection(connection: sqlite3.Connection) -> None:
    """Enable the durability settings required by every recording writer."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 0")
    journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if str(journal_mode).casefold() != "wal":
        raise RecordingArchiveError("recording archive could not enable WAL mode")
    connection.execute("PRAGMA synchronous = FULL")
