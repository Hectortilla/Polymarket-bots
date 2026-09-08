"""SQLite DDL for the durable recording archive."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from polybot.recording.archive.columns import ArchiveColumn

from ..contracts.kinds import payload_kind_sql_literals
from ..contracts.session import session_status_sql_literals

RECORDING_FEATURES_TABLE = "recording_features"
CAPTURE_ANOMALIES_TABLE = "capture_anomalies"
ARCHIVE_META_TABLE = "archive_meta"
SESSIONS_TABLE = "sessions"
EVENTS_TABLE = "events"
EVENT_TOKENS_TABLE = "event_tokens"
METADATA_REVISIONS_TABLE = "metadata_revisions"
BOOK_CHECKPOINTS_TABLE = "book_checkpoints"
COVERAGE_GAPS_TABLE = "coverage_gaps"
SCHEMA_VERSION = 2
SQLITE_APPLICATION_ID = 0x504F4C59


@dataclass(frozen=True, slots=True)
class _TableSchema:
    name: str
    columns: tuple[tuple[str, str], ...]
    constraints: tuple[str, ...] = ()
    suffix: str = "STRICT"

    @property
    def column_names(self) -> frozenset[str]:
        return frozenset(name for name, _ in self.columns)

    def create_sql(self) -> str:
        members = [f"{name} {declaration}" for name, declaration in self.columns]
        members.extend(self.constraints)
        return f"CREATE TABLE {self.name} (\n    {', '.join(members)}\n) {self.suffix};"


_CORE_TABLES = (
    _TableSchema(
        ARCHIVE_META_TABLE,
        (
            (
                ArchiveColumn.SINGLETON,
                f"INTEGER PRIMARY KEY CHECK ({ArchiveColumn.SINGLETON} = 1)",
            ),
            (ArchiveColumn.SCHEMA_VERSION, "INTEGER NOT NULL"),
            (ArchiveColumn.TARGET_IDENTITY, "TEXT NOT NULL"),
            (
                ArchiveColumn.CREATED_AT_MS,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.CREATED_AT_MS} >= 0)",
            ),
        ),
    ),
    _TableSchema(
        SESSIONS_TABLE,
        (
            (ArchiveColumn.SESSION_ID, "INTEGER PRIMARY KEY AUTOINCREMENT"),
            (
                ArchiveColumn.STARTED_AT_MS,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.STARTED_AT_MS} >= 0)",
            ),
            (
                ArchiveColumn.ENDED_AT_MS,
                f"INTEGER CHECK ({ArchiveColumn.ENDED_AT_MS} IS NULL OR {ArchiveColumn.ENDED_AT_MS} >= {ArchiveColumn.STARTED_AT_MS})",
            ),
            (
                ArchiveColumn.CLEAN_CLOSE,
                f"INTEGER NOT NULL DEFAULT 0 CHECK ({ArchiveColumn.CLEAN_CLOSE} IN (0, 1))",
            ),
            (
                ArchiveColumn.INTEGRITY_STATUS,
                "TEXT NOT NULL CHECK "
                f"({ArchiveColumn.INTEGRITY_STATUS} IN ({session_status_sql_literals()}))",
            ),
            (ArchiveColumn.RECORDER_VERSION, "TEXT NOT NULL"),
            (ArchiveColumn.SDK_VERSION, "TEXT NOT NULL"),
            (ArchiveColumn.FAILURE_REASON, "TEXT"),
        ),
    ),
    _TableSchema(
        EVENTS_TABLE,
        (
            (
                ArchiveColumn.SEQUENCE,
                f"INTEGER PRIMARY KEY CHECK ({ArchiveColumn.SEQUENCE} > 0)",
            ),
            (
                ArchiveColumn.SESSION_ID,
                f"INTEGER NOT NULL REFERENCES {SESSIONS_TABLE}({ArchiveColumn.SESSION_ID})",
            ),
            (
                ArchiveColumn.SUBSCRIPTION_GENERATION,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.SUBSCRIPTION_GENERATION} >= 0)",
            ),
            (
                ArchiveColumn.OBSERVED_AT_MS,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.OBSERVED_AT_MS} >= 0)",
            ),
            (
                ArchiveColumn.SOURCE_TIMESTAMP_MS,
                "INTEGER CHECK "
                f"({ArchiveColumn.SOURCE_TIMESTAMP_MS} IS NULL OR {ArchiveColumn.SOURCE_TIMESTAMP_MS} >= 0)",
            ),
            (ArchiveColumn.CONDITION_ID, "TEXT"),
            (ArchiveColumn.MARKET_SLUG, "TEXT"),
            (ArchiveColumn.TOKEN_ID, "TEXT"),
            (
                ArchiveColumn.PAYLOAD_KIND,
                "TEXT NOT NULL CHECK "
                f"({ArchiveColumn.PAYLOAD_KIND} IN ({payload_kind_sql_literals()}))",
            ),
            (ArchiveColumn.PAYLOAD_JSON, "TEXT NOT NULL"),
        ),
    ),
    _TableSchema(
        EVENT_TOKENS_TABLE,
        (
            (
                ArchiveColumn.SEQUENCE,
                f"INTEGER NOT NULL REFERENCES {EVENTS_TABLE}({ArchiveColumn.SEQUENCE}) ON DELETE CASCADE",
            ),
            (ArchiveColumn.TOKEN_ID, "TEXT NOT NULL"),
        ),
        (f"PRIMARY KEY ({ArchiveColumn.SEQUENCE}, {ArchiveColumn.TOKEN_ID})",),
        "WITHOUT ROWID",
    ),
    _TableSchema(
        METADATA_REVISIONS_TABLE,
        (
            (ArchiveColumn.CONDITION_ID, "TEXT NOT NULL"),
            (
                ArchiveColumn.SEQUENCE,
                f"INTEGER NOT NULL UNIQUE REFERENCES {EVENTS_TABLE}({ArchiveColumn.SEQUENCE})",
            ),
            (
                ArchiveColumn.OBSERVED_AT_MS,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.OBSERVED_AT_MS} >= 0)",
            ),
            (ArchiveColumn.PAYLOAD_JSON, "TEXT NOT NULL"),
        ),
        (f"PRIMARY KEY ({ArchiveColumn.CONDITION_ID}, {ArchiveColumn.SEQUENCE})",),
        "WITHOUT ROWID",
    ),
    _TableSchema(
        BOOK_CHECKPOINTS_TABLE,
        (
            (ArchiveColumn.TOKEN_ID, "TEXT NOT NULL"),
            (
                ArchiveColumn.SEQUENCE,
                f"INTEGER NOT NULL REFERENCES {EVENTS_TABLE}({ArchiveColumn.SEQUENCE})",
            ),
            (
                ArchiveColumn.SESSION_ID,
                f"INTEGER NOT NULL REFERENCES {SESSIONS_TABLE}({ArchiveColumn.SESSION_ID})",
            ),
            (
                ArchiveColumn.SUBSCRIPTION_GENERATION,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.SUBSCRIPTION_GENERATION} >= 0)",
            ),
            (
                ArchiveColumn.OBSERVED_AT_MS,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.OBSERVED_AT_MS} >= 0)",
            ),
            (ArchiveColumn.CONDITION_ID, "TEXT NOT NULL"),
            (ArchiveColumn.MARKET_SLUG, "TEXT NOT NULL"),
            (ArchiveColumn.PAYLOAD_JSON, "TEXT NOT NULL"),
        ),
        (
            f"PRIMARY KEY ({ArchiveColumn.TOKEN_ID}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.SEQUENCE})",
        ),
        "WITHOUT ROWID",
    ),
    _TableSchema(
        COVERAGE_GAPS_TABLE,
        (
            (ArchiveColumn.GAP_ID, "INTEGER PRIMARY KEY AUTOINCREMENT"),
            (
                ArchiveColumn.EVENT_SEQUENCE,
                f"INTEGER NOT NULL UNIQUE REFERENCES {EVENTS_TABLE}({ArchiveColumn.SEQUENCE})",
            ),
            (
                ArchiveColumn.SESSION_ID,
                f"INTEGER NOT NULL REFERENCES {SESSIONS_TABLE}({ArchiveColumn.SESSION_ID})",
            ),
            (
                ArchiveColumn.SUBSCRIPTION_GENERATION,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.SUBSCRIPTION_GENERATION} >= 0)",
            ),
            (
                ArchiveColumn.OBSERVED_AT_MS,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.OBSERVED_AT_MS} >= 0)",
            ),
            (ArchiveColumn.CONDITION_ID, "TEXT"),
            (ArchiveColumn.MARKET_SLUG, "TEXT"),
            (
                ArchiveColumn.STARTED_AT_MS,
                f"INTEGER NOT NULL CHECK ({ArchiveColumn.STARTED_AT_MS} >= 0)",
            ),
            (
                ArchiveColumn.ENDED_AT_MS,
                f"INTEGER CHECK ({ArchiveColumn.ENDED_AT_MS} IS NULL OR {ArchiveColumn.ENDED_AT_MS} >= {ArchiveColumn.STARTED_AT_MS})",
            ),
            (ArchiveColumn.REASON, "TEXT NOT NULL"),
            (ArchiveColumn.PAYLOAD_JSON, "TEXT NOT NULL"),
        ),
    ),
)

CORE_ARCHIVE_TABLE_COLUMNS = {table.name: table.column_names for table in _CORE_TABLES}


def initialize_archive_schema(
    connection: sqlite3.Connection,
    *,
    application_id: int,
    schema_version: int,
    target_identity: str,
    created_at_ms: int,
) -> None:
    core_table_ddl = "\n".join(table.create_sql() for table in _CORE_TABLES)
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;
        PRAGMA application_id = {application_id};
        PRAGMA user_version = {schema_version};

        {core_table_ddl}

        CREATE INDEX events_observed_idx
            ON {EVENTS_TABLE}({ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.SEQUENCE});
        CREATE INDEX events_condition_idx
            ON {EVENTS_TABLE}({ArchiveColumn.CONDITION_ID}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.SEQUENCE});
        CREATE INDEX events_slug_idx
            ON {EVENTS_TABLE}({ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.SEQUENCE});
        CREATE INDEX event_tokens_token_idx
            ON {EVENT_TOKENS_TABLE}({ArchiveColumn.TOKEN_ID}, {ArchiveColumn.SEQUENCE});
        CREATE INDEX metadata_time_idx
            ON {METADATA_REVISIONS_TABLE}({ArchiveColumn.CONDITION_ID}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.SEQUENCE});
        CREATE INDEX checkpoints_time_idx
            ON {BOOK_CHECKPOINTS_TABLE}({ArchiveColumn.TOKEN_ID}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.SEQUENCE});
        CREATE INDEX coverage_gaps_time_idx
            ON {COVERAGE_GAPS_TABLE}({ArchiveColumn.STARTED_AT_MS}, {ArchiveColumn.ENDED_AT_MS});

        INSERT INTO {ARCHIVE_META_TABLE} (
            {ArchiveColumn.SINGLETON}, {ArchiveColumn.SCHEMA_VERSION}, {ArchiveColumn.TARGET_IDENTITY}, {ArchiveColumn.CREATED_AT_MS}
        ) VALUES (
            1,
            {schema_version},
            {_sql_quote(target_identity)},
            {created_at_ms}
        );
        COMMIT;
        """
    )


def ensure_capture_anomaly_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RECORDING_FEATURES_TABLE} (
            {ArchiveColumn.FEATURE_NAME} TEXT PRIMARY KEY,
            {ArchiveColumn.AVAILABLE_FROM_SESSION_ID} INTEGER NOT NULL
                REFERENCES {SESSIONS_TABLE}({ArchiveColumn.SESSION_ID}),
            {ArchiveColumn.ENABLED_AT_MS} INTEGER NOT NULL CHECK ({ArchiveColumn.ENABLED_AT_MS} >= 0),
            {ArchiveColumn.RECORDER_VERSION} TEXT NOT NULL
        ) STRICT
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CAPTURE_ANOMALIES_TABLE} (
            {ArchiveColumn.ANOMALY_ID} INTEGER PRIMARY KEY AUTOINCREMENT,
            {ArchiveColumn.SESSION_ID} INTEGER NOT NULL REFERENCES {SESSIONS_TABLE}({ArchiveColumn.SESSION_ID}),
            {ArchiveColumn.SUBSCRIPTION_GENERATION} INTEGER NOT NULL CHECK (
                {ArchiveColumn.SUBSCRIPTION_GENERATION} >= 0
            ),
            {ArchiveColumn.OBSERVED_AT_MS} INTEGER NOT NULL CHECK ({ArchiveColumn.OBSERVED_AT_MS} >= 0),
            {ArchiveColumn.CONDITION_ID} TEXT,
            {ArchiveColumn.MARKET_SLUG} TEXT,
            {ArchiveColumn.TOKEN_ID} TEXT,
            {ArchiveColumn.FAILURE_KIND} TEXT NOT NULL,
            {ArchiveColumn.PAYLOAD_JSON} TEXT NOT NULL
        ) STRICT
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS capture_anomalies_session_time_idx
        ON {CAPTURE_ANOMALIES_TABLE}({ArchiveColumn.SESSION_ID}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.ANOMALY_ID})
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS capture_anomalies_condition_idx
        ON {CAPTURE_ANOMALIES_TABLE}({ArchiveColumn.CONDITION_ID}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.ANOMALY_ID})
        """
    )


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
