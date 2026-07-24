"""Checkpoint row decoding and metadata validation."""

from __future__ import annotations

import sqlite3

from ..contracts.book import BookBaselinePayload
from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketIdentity, MarketMetadataPayload
from ..contracts.records import BookCheckpoint
from .errors import ArchiveFormatError, ArchiveIntegrityError
from .primitives import _strict_int
from .rows import _typed_payload


def checkpoint_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    token_id: str,
    *,
    replay_cutoff_sequence: int,
) -> BookCheckpoint:
    """Decode and validate a checkpoint row against its prior metadata."""

    market = market_before_checkpoint(
        connection,
        row["condition_id"],
        _strict_int(row["sequence"], "checkpoint sequence"),
    )
    return checkpoint_from_validated_row(
        row,
        token_id,
        replay_cutoff_sequence=replay_cutoff_sequence,
        market=market,
    )


def market_before_checkpoint(
    connection: sqlite3.Connection,
    condition_id: str,
    sequence: int,
) -> MarketMetadataPayload:
    metadata_row = connection.execute(
        """
        SELECT payload_json FROM metadata_revisions
        WHERE condition_id = ? AND sequence <= ?
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (condition_id, sequence),
    ).fetchone()
    if metadata_row is None:
        raise ArchiveIntegrityError("book checkpoint has no preceding market metadata")
    return _typed_payload(
        PayloadKind.MARKET_METADATA,
        metadata_row["payload_json"],
        MarketMetadataPayload,
    )


def checkpoint_from_validated_row(
    row: sqlite3.Row,
    token_id: str,
    *,
    replay_cutoff_sequence: int,
    market: MarketMetadataPayload,
) -> BookCheckpoint:
    sequence = _strict_int(row["sequence"], "checkpoint sequence")
    if sequence > replay_cutoff_sequence:
        raise ArchiveIntegrityError("book checkpoint exceeds the replay cutoff")
    book = _typed_payload(
        PayloadKind.BOOK_BASELINE,
        row["payload_json"],
        BookBaselinePayload,
    )
    if (
        row["condition_id"] != market.condition_id
        or row["market_slug"] != market.market_slug
        or token_id not in {outcome.token_id for outcome in market.outcomes}
        or book.token_id != token_id
    ):
        raise ArchiveIntegrityError(
            "book checkpoint identity does not match market metadata"
        )
    try:
        return BookCheckpoint(
            sequence=sequence,
            session_id=_strict_int(row["session_id"], "checkpoint session"),
            subscription_generation=_strict_int(
                row["subscription_generation"],
                "checkpoint generation",
            ),
            observed_at_ms=_strict_int(
                row["observed_at_ms"],
                "checkpoint timestamp",
            ),
            identity=MarketIdentity(
                condition_id=row["condition_id"],
                market_slug=row["market_slug"],
                token_id=token_id,
            ),
            book=book,
        )
    except ValueError as error:
        raise ArchiveFormatError("book checkpoint is malformed") from error
