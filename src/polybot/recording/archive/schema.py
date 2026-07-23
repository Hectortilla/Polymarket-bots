"""SQLite DDL for the durable recording archive."""

from __future__ import annotations

import sqlite3

from ..contracts.kinds import payload_kind_sql_literals
from ..contracts.session import session_status_sql_literals


RECORDING_FEATURES_TABLE = "recording_features"
CAPTURE_ANOMALIES_TABLE = "capture_anomalies"
SCHEMA_VERSION = 2
SQLITE_APPLICATION_ID = 0x504F4C59

CORE_ARCHIVE_TABLE_COLUMNS = {
    "archive_meta": frozenset(
        {"singleton", "schema_version", "target_identity", "created_at_ms"}
    ),
    "sessions": frozenset(
        {
            "session_id",
            "started_at_ms",
            "ended_at_ms",
            "clean_close",
            "integrity_status",
            "recorder_version",
            "sdk_version",
            "failure_reason",
        }
    ),
    "events": frozenset(
        {
            "sequence",
            "session_id",
            "subscription_generation",
            "observed_at_ms",
            "source_timestamp_ms",
            "condition_id",
            "market_slug",
            "token_id",
            "payload_kind",
            "payload_json",
        }
    ),
    "event_tokens": frozenset({"sequence", "token_id"}),
    "metadata_revisions": frozenset(
        {"condition_id", "sequence", "observed_at_ms", "payload_json"}
    ),
    "book_checkpoints": frozenset(
        {
            "token_id",
            "sequence",
            "session_id",
            "subscription_generation",
            "observed_at_ms",
            "condition_id",
            "market_slug",
            "payload_json",
        }
    ),
    "coverage_gaps": frozenset(
        {
            "gap_id",
            "event_sequence",
            "session_id",
            "subscription_generation",
            "observed_at_ms",
            "condition_id",
            "market_slug",
            "started_at_ms",
            "ended_at_ms",
            "reason",
            "payload_json",
        }
    ),
}


def initialize_archive_schema(
    connection: sqlite3.Connection,
    *,
    application_id: int,
    schema_version: int,
    target_identity: str,
    created_at_ms: int,
) -> None:
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;
        PRAGMA application_id = {application_id};
        PRAGMA user_version = {schema_version};

        CREATE TABLE archive_meta (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            schema_version INTEGER NOT NULL,
            target_identity TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
        ) STRICT;

        CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
            ended_at_ms INTEGER CHECK (
                ended_at_ms IS NULL OR ended_at_ms >= started_at_ms
            ),
            clean_close INTEGER NOT NULL DEFAULT 0 CHECK (clean_close IN (0, 1)),
            integrity_status TEXT NOT NULL CHECK (
                integrity_status IN ({session_status_sql_literals()})
            ),
            recorder_version TEXT NOT NULL,
            sdk_version TEXT NOT NULL,
            failure_reason TEXT
        ) STRICT;

        CREATE TABLE events (
            sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            subscription_generation INTEGER NOT NULL CHECK (
                subscription_generation >= 0
            ),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            source_timestamp_ms INTEGER CHECK (
                source_timestamp_ms IS NULL OR source_timestamp_ms >= 0
            ),
            condition_id TEXT,
            market_slug TEXT,
            token_id TEXT,
            payload_kind TEXT NOT NULL CHECK (
                payload_kind IN ({payload_kind_sql_literals()})
            ),
            payload_json TEXT NOT NULL
        ) STRICT;

        CREATE TABLE event_tokens (
            sequence INTEGER NOT NULL REFERENCES events(sequence) ON DELETE CASCADE,
            token_id TEXT NOT NULL,
            PRIMARY KEY (sequence, token_id)
        ) WITHOUT ROWID;

        CREATE TABLE metadata_revisions (
            condition_id TEXT NOT NULL,
            sequence INTEGER NOT NULL UNIQUE REFERENCES events(sequence),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            payload_json TEXT NOT NULL,
            PRIMARY KEY (condition_id, sequence)
        ) WITHOUT ROWID;

        CREATE TABLE book_checkpoints (
            token_id TEXT NOT NULL,
            sequence INTEGER NOT NULL REFERENCES events(sequence),
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            subscription_generation INTEGER NOT NULL CHECK (
                subscription_generation >= 0
            ),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            condition_id TEXT NOT NULL,
            market_slug TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (token_id, observed_at_ms, sequence)
        ) WITHOUT ROWID;

        CREATE TABLE coverage_gaps (
            gap_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_sequence INTEGER NOT NULL UNIQUE REFERENCES events(sequence),
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            subscription_generation INTEGER NOT NULL CHECK (
                subscription_generation >= 0
            ),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            condition_id TEXT,
            market_slug TEXT,
            started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
            ended_at_ms INTEGER CHECK (
                ended_at_ms IS NULL OR ended_at_ms >= started_at_ms
            ),
            reason TEXT NOT NULL,
            payload_json TEXT NOT NULL
        ) STRICT;

        CREATE INDEX events_observed_idx ON events(observed_at_ms, sequence);
        CREATE INDEX events_condition_idx
            ON events(condition_id, observed_at_ms, sequence);
        CREATE INDEX events_slug_idx ON events(market_slug, observed_at_ms, sequence);
        CREATE INDEX event_tokens_token_idx ON event_tokens(token_id, sequence);
        CREATE INDEX metadata_time_idx
            ON metadata_revisions(condition_id, observed_at_ms, sequence);
        CREATE INDEX checkpoints_time_idx
            ON book_checkpoints(token_id, observed_at_ms, sequence);
        CREATE INDEX coverage_gaps_time_idx
            ON coverage_gaps(started_at_ms, ended_at_ms);

        INSERT INTO archive_meta (
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
