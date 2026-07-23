"""Cross-row integrity validation for archived recording events."""

from __future__ import annotations

import sqlite3

from ..contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
)
from ..contracts.gaps import CoverageGapPayload
from ..contracts.market import (
    MarketIdentity,
    MarketMetadataPayload,
)
from ..contracts.records import RecordedEvent
from ..contracts.payloads import (
    ResolutionPayload,
    event_token_ids,
)
from ..contracts.kinds import PayloadKind
from ..coverage import CoverageScope
from .errors import ArchiveFormatError, ArchiveIntegrityError
from .primitives import _required_text, _strict_int
from .rows import _event_from_row, _typed_payload
from .schema import (
    CORE_ARCHIVE_TABLE_COLUMNS,
    SCHEMA_VERSION,
    SQLITE_APPLICATION_ID,
)
from .selection import _gap_affects


def _validate_event_dependencies(
    event: RecordedEvent,
    metadata: dict[str, MarketMetadataPayload],
    baselines: set[tuple[int, str]],
) -> None:
    if isinstance(event.payload, CoverageGapPayload):
        return
    identity = event.identity
    if identity is None or identity.condition_id is None:
        raise ArchiveIntegrityError(
            "market event requires a resolved condition identity"
        )
    if isinstance(event.payload, MarketMetadataPayload):
        _validate_metadata_revision(event.payload, metadata)
        return
    if identity.condition_id not in metadata:
        raise ArchiveIntegrityError(
            "market metadata must be committed before dependent events"
        )
    _validate_payload_market_identity(event, metadata[identity.condition_id])
    if isinstance(event.payload, BookDeltaPayload):
        missing = [
            token_id
            for token_id in event_token_ids(event.payload)
            if (event.subscription_generation, token_id) not in baselines
        ]
        if missing:
            raise ArchiveIntegrityError(
                "book delta is missing a baseline in its subscription generation: "
                + ", ".join(missing)
            )


def _validate_metadata_revision(
    revision: MarketMetadataPayload,
    metadata: dict[str, MarketMetadataPayload],
) -> None:
    token_ids = {outcome.token_id for outcome in revision.outcomes}
    for condition_id, existing in metadata.items():
        existing_token_ids = {outcome.token_id for outcome in existing.outcomes}
        if condition_id != revision.condition_id and token_ids & existing_token_ids:
            raise ArchiveIntegrityError("market token ID maps to multiple conditions")
    previous = metadata.get(revision.condition_id)
    if previous is None:
        return
    if (
        previous.market_id != revision.market_id
        or previous.market_slug != revision.market_slug
        or tuple(
            (outcome.label, outcome.token_id) for outcome in previous.outcomes
        )
        != tuple((outcome.label, outcome.token_id) for outcome in revision.outcomes)
    ):
        raise ArchiveIntegrityError(
            "market metadata revision changed immutable identity"
        )


def _validate_payload_market_identity(
    event: RecordedEvent,
    market: MarketMetadataPayload,
) -> None:
    identity = event.identity
    if identity is None:
        raise ArchiveIntegrityError("market event has no identity")
    if (
        identity.condition_id != market.condition_id
        or identity.market_slug != market.market_slug
    ):
        raise ArchiveIntegrityError("event identity does not match market metadata")
    market_tokens = {outcome.token_id for outcome in market.outcomes}
    payload_tokens = set(event_token_ids(event.payload))
    if not payload_tokens <= market_tokens:
        raise ArchiveIntegrityError(
            "event token identity does not match market metadata"
        )
    if not isinstance(event.payload, ResolutionPayload):
        return
    if payload_tokens != market_tokens:
        raise ArchiveIntegrityError(
            "resolution token pair does not match market metadata"
        )
    outcome_by_token = {
        outcome.token_id: outcome.label for outcome in market.outcomes
    }
    expected_outcome = outcome_by_token[event.payload.winning_token_id]
    if event.payload.winning_outcome != expected_outcome:
        raise ArchiveIntegrityError("resolution outcome does not match market metadata")


def _invalidate_gap_baselines(
    gap: CoverageGapPayload,
    metadata: dict[str, MarketMetadataPayload],
    baselines: set[tuple[int, str]],
    *,
    identity: MarketIdentity | None,
) -> None:
    affected_tokens = CoverageScope.from_gap(
        gap,
        identity,
    ).resolved_token_ids(metadata.values())
    if affected_tokens is None:
        baselines.clear()
        return
    baselines.difference_update(
        {key for key in baselines if key[1] in affected_tokens}
    )


def _validate_stored_event_dependencies(
    connection: sqlite3.Connection,
    event: RecordedEvent,
    verified_metadata: dict[str, MarketMetadataPayload],
    verified_baselines: set[tuple[int, int, str]],
) -> None:
    if isinstance(event.payload, MarketMetadataPayload):
        _validate_metadata_revision(event.payload, verified_metadata)
        verified_metadata[event.payload.condition_id] = event.payload
        return
    if isinstance(event.payload, CoverageGapPayload):
        _invalidate_stored_gap_baselines(
            event,
            verified_metadata,
            verified_baselines,
        )
        return
    identity = event.identity
    if identity is None or identity.condition_id is None:
        raise ArchiveFormatError("stored market event lacks condition identity")
    if identity.condition_id not in verified_metadata:
        row = connection.execute(
            """
            SELECT payload_json FROM metadata_revisions
            WHERE condition_id = ? AND sequence < ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (identity.condition_id, event.sequence),
        ).fetchone()
        if row is None:
            raise ArchiveIntegrityError(
                f"event {event.sequence} has no preceding market metadata"
            )
        market = _typed_payload(
            PayloadKind.MARKET_METADATA,
            row["payload_json"],
            MarketMetadataPayload,
        )
        if market.condition_id != identity.condition_id:
            raise ArchiveFormatError("metadata revision identity is inconsistent")
        verified_metadata[identity.condition_id] = market
    _validate_payload_market_identity(
        event,
        verified_metadata[identity.condition_id],
    )
    if isinstance(event.payload, BookBaselinePayload):
        verified_baselines.add(
            (
                event.session_id,
                event.subscription_generation,
                event.payload.token_id,
            )
        )
        return
    if not isinstance(event.payload, BookDeltaPayload):
        return
    for token_id in event_token_ids(event.payload):
        baseline_key = (
            event.session_id,
            event.subscription_generation,
            token_id,
        )
        if baseline_key in verified_baselines:
            continue
        row = connection.execute(
            """
            SELECT event.sequence
            FROM events AS event
            JOIN event_tokens AS token ON token.sequence = event.sequence
            WHERE event.payload_kind = ?
              AND event.subscription_generation = ?
              AND event.session_id = ?
              AND token.token_id = ?
              AND event.sequence < ?
            ORDER BY event.sequence DESC
            LIMIT 1
            """,
            (
                PayloadKind.BOOK_BASELINE.value,
                event.subscription_generation,
                event.session_id,
                token_id,
                event.sequence,
            ),
        ).fetchone()
        if row is None or _has_affecting_gap_after_baseline(
            connection,
            baseline_sequence=_strict_int(
                row["sequence"],
                "baseline sequence",
            ),
            event=event,
            token_id=token_id,
        ):
            raise ArchiveIntegrityError(
                f"book delta event {event.sequence} has no preceding baseline"
            )
        verified_baselines.add(baseline_key)


def _has_affecting_gap_after_baseline(
    connection: sqlite3.Connection,
    *,
    baseline_sequence: int,
    event: RecordedEvent,
    token_id: str,
) -> bool:
    identity = event.identity
    if identity is None:
        raise AssertionError("book delta has no market identity")
    rows = connection.execute(
        """
        SELECT * FROM events
        WHERE payload_kind = ? AND sequence > ? AND sequence < ?
        ORDER BY sequence
        """,
        (
            PayloadKind.COVERAGE_GAP.value,
            baseline_sequence,
            event.sequence,
        ),
    )
    for row in rows:
        gap_event = _event_from_row(row)
        if not isinstance(gap_event.payload, CoverageGapPayload):
            raise ArchiveFormatError("coverage-gap index contains a wrong payload")
        if _gap_affects(
            gap_event.identity,
            gap_event.payload,
            condition_ids=(identity.condition_id,),
            market_slugs=(identity.market_slug,),
            token_id=token_id,
        ):
            return True
    return False


def _invalidate_stored_gap_baselines(
    event: RecordedEvent,
    metadata: dict[str, MarketMetadataPayload],
    baselines: set[tuple[int, int, str]],
) -> None:
    gap = event.payload
    if not isinstance(gap, CoverageGapPayload):
        raise AssertionError("baseline invalidation requires a coverage gap")
    affected_tokens = CoverageScope.from_gap(
        gap,
        event.identity,
    ).resolved_token_ids(metadata.values())
    if affected_tokens is None:
        baselines.clear()
        return
    baselines.difference_update(
        {key for key in baselines if key[2] in affected_tokens}
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
