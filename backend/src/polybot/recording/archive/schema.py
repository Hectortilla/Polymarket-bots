"""SQLite DDL for the durable recording archive."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

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
        return (
            f"CREATE TABLE {self.name} (\n"
            f"    {', '.join(members)}\n"
            f") {self.suffix};"
        )


_CORE_TABLES = (
    _TableSchema(
        ARCHIVE_META_TABLE,
        (
            ("singleton", "INTEGER PRIMARY KEY CHECK (singleton = 1)"),
            ("schema_version", "INTEGER NOT NULL"),
            ("target_identity", "TEXT NOT NULL"),
            ("created_at_ms", "INTEGER NOT NULL CHECK (created_at_ms >= 0)"),
        ),
    ),
    _TableSchema(
        SESSIONS_TABLE,
        (
            ("session_id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
            ("started_at_ms", "INTEGER NOT NULL CHECK (started_at_ms >= 0)"),
            (
                "ended_at_ms",
                "INTEGER CHECK (ended_at_ms IS NULL OR ended_at_ms >= started_at_ms)",
            ),
            (
                "clean_close",
                "INTEGER NOT NULL DEFAULT 0 CHECK (clean_close IN (0, 1))",
            ),
            (
                "integrity_status",
                "TEXT NOT NULL CHECK "
                f"(integrity_status IN ({session_status_sql_literals()}))",
            ),
            ("recorder_version", "TEXT NOT NULL"),
            ("sdk_version", "TEXT NOT NULL"),
            ("failure_reason", "TEXT"),
        ),
    ),
    _TableSchema(
        EVENTS_TABLE,
        (
            ("sequence", "INTEGER PRIMARY KEY CHECK (sequence > 0)"),
            ("session_id", f"INTEGER NOT NULL REFERENCES {SESSIONS_TABLE}(session_id)"),
            (
                "subscription_generation",
                "INTEGER NOT NULL CHECK (subscription_generation >= 0)",
            ),
            ("observed_at_ms", "INTEGER NOT NULL CHECK (observed_at_ms >= 0)"),
            (
                "source_timestamp_ms",
                "INTEGER CHECK "
                "(source_timestamp_ms IS NULL OR source_timestamp_ms >= 0)",
            ),
            ("condition_id", "TEXT"),
            ("market_slug", "TEXT"),
            ("token_id", "TEXT"),
            (
                "payload_kind",
                "TEXT NOT NULL CHECK "
                f"(payload_kind IN ({payload_kind_sql_literals()}))",
            ),
            ("payload_json", "TEXT NOT NULL"),
        ),
    ),
    _TableSchema(
        EVENT_TOKENS_TABLE,
        (
            (
                "sequence",
                f"INTEGER NOT NULL REFERENCES {EVENTS_TABLE}(sequence) ON DELETE CASCADE",
            ),
            ("token_id", "TEXT NOT NULL"),
        ),
        ("PRIMARY KEY (sequence, token_id)",),
        "WITHOUT ROWID",
    ),
    _TableSchema(
        METADATA_REVISIONS_TABLE,
        (
            ("condition_id", "TEXT NOT NULL"),
            (
                "sequence",
                f"INTEGER NOT NULL UNIQUE REFERENCES {EVENTS_TABLE}(sequence)",
            ),
            ("observed_at_ms", "INTEGER NOT NULL CHECK (observed_at_ms >= 0)"),
            ("payload_json", "TEXT NOT NULL"),
        ),
        ("PRIMARY KEY (condition_id, sequence)",),
        "WITHOUT ROWID",
    ),
    _TableSchema(
        BOOK_CHECKPOINTS_TABLE,
        (
            ("token_id", "TEXT NOT NULL"),
            ("sequence", f"INTEGER NOT NULL REFERENCES {EVENTS_TABLE}(sequence)"),
            ("session_id", f"INTEGER NOT NULL REFERENCES {SESSIONS_TABLE}(session_id)"),
            (
                "subscription_generation",
                "INTEGER NOT NULL CHECK (subscription_generation >= 0)",
            ),
            ("observed_at_ms", "INTEGER NOT NULL CHECK (observed_at_ms >= 0)"),
            ("condition_id", "TEXT NOT NULL"),
            ("market_slug", "TEXT NOT NULL"),
            ("payload_json", "TEXT NOT NULL"),
        ),
        ("PRIMARY KEY (token_id, observed_at_ms, sequence)",),
        "WITHOUT ROWID",
    ),
    _TableSchema(
        COVERAGE_GAPS_TABLE,
        (
            ("gap_id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
            (
                "event_sequence",
                f"INTEGER NOT NULL UNIQUE REFERENCES {EVENTS_TABLE}(sequence)",
            ),
            ("session_id", f"INTEGER NOT NULL REFERENCES {SESSIONS_TABLE}(session_id)"),
            (
                "subscription_generation",
                "INTEGER NOT NULL CHECK (subscription_generation >= 0)",
            ),
            ("observed_at_ms", "INTEGER NOT NULL CHECK (observed_at_ms >= 0)"),
            ("condition_id", "TEXT"),
            ("market_slug", "TEXT"),
            ("started_at_ms", "INTEGER NOT NULL CHECK (started_at_ms >= 0)"),
            (
                "ended_at_ms",
                "INTEGER CHECK (ended_at_ms IS NULL OR ended_at_ms >= started_at_ms)",
            ),
            ("reason", "TEXT NOT NULL"),
            ("payload_json", "TEXT NOT NULL"),
        ),
    ),
)

CORE_ARCHIVE_TABLE_COLUMNS = {
    table.name: table.column_names for table in _CORE_TABLES
}


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
            ON {EVENTS_TABLE}(observed_at_ms, sequence);
        CREATE INDEX events_condition_idx
            ON {EVENTS_TABLE}(condition_id, observed_at_ms, sequence);
        CREATE INDEX events_slug_idx
            ON {EVENTS_TABLE}(market_slug, observed_at_ms, sequence);
        CREATE INDEX event_tokens_token_idx
            ON {EVENT_TOKENS_TABLE}(token_id, sequence);
        CREATE INDEX metadata_time_idx
            ON {METADATA_REVISIONS_TABLE}(condition_id, observed_at_ms, sequence);
        CREATE INDEX checkpoints_time_idx
            ON {BOOK_CHECKPOINTS_TABLE}(token_id, observed_at_ms, sequence);
        CREATE INDEX coverage_gaps_time_idx
            ON {COVERAGE_GAPS_TABLE}(started_at_ms, ended_at_ms);

        INSERT INTO {ARCHIVE_META_TABLE} (
            singleton, schema_version, target_identity, created_at_ms
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
            feature_name TEXT PRIMARY KEY,
            available_from_session_id INTEGER NOT NULL
                REFERENCES sessions(session_id),
            enabled_at_ms INTEGER NOT NULL CHECK (enabled_at_ms >= 0),
            recorder_version TEXT NOT NULL
        ) STRICT
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CAPTURE_ANOMALIES_TABLE} (
            anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            subscription_generation INTEGER NOT NULL CHECK (
                subscription_generation >= 0
            ),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            condition_id TEXT,
            market_slug TEXT,
            token_id TEXT,
            failure_kind TEXT NOT NULL,
            payload_json TEXT NOT NULL
        ) STRICT
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS capture_anomalies_session_time_idx
        ON {CAPTURE_ANOMALIES_TABLE}(session_id, observed_at_ms, anomaly_id)
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS capture_anomalies_condition_idx
        ON {CAPTURE_ANOMALIES_TABLE}(condition_id, observed_at_ms, anomaly_id)
        """
    )


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
