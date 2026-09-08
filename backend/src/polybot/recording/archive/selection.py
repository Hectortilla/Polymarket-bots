"""Validated event selections and their SQLite query representation."""

from __future__ import annotations

from collections.abc import Iterable

from ..contracts.gaps import CoverageGapPayload
from ..contracts.market import MarketIdentity
from ..contracts.kinds import PayloadKind
from ..coverage import CoverageScope
from .primitives import _nonnegative_timestamp, _positive_int, _required_text


def _selection(
    *,
    start_at_ms: int | None,
    end_at_ms: int | None,
    session_id: int | None,
    condition_id: str | None,
    condition_ids: Iterable[str] | None,
    market_slug: str | None,
    market_slugs: Iterable[str] | None,
    token_id: str | None,
) -> dict[str, object]:
    if start_at_ms is not None:
        _nonnegative_timestamp(start_at_ms, "selection start")
    if end_at_ms is not None:
        _nonnegative_timestamp(end_at_ms, "selection end")
    if start_at_ms is not None and end_at_ms is not None and end_at_ms < start_at_ms:
        raise ValueError("recording selection cannot end before it starts")
    return {
        "start_at_ms": start_at_ms,
        "end_at_ms": end_at_ms,
        "session_id": (
            None if session_id is None else _positive_int(session_id, "session ID")
        ),
        "condition_ids": _text_selection(
            singular=condition_id,
            plural=condition_ids,
            singular_name="condition ID",
            plural_name="condition IDs",
        ),
        "market_slugs": _text_selection(
            singular=market_slug,
            plural=market_slugs,
            singular_name="market slug",
            plural_name="market slugs",
        ),
        "token_id": None if token_id is None else _required_text(token_id, "token ID"),
    }


def _text_selection(
    *,
    singular: str | None,
    plural: Iterable[str] | None,
    singular_name: str,
    plural_name: str,
) -> tuple[str, ...] | None:
    if singular is not None and plural is not None:
        raise ValueError(f"use either {singular_name} or {plural_name}, not both")
    if singular is not None:
        return (_required_text(singular, singular_name),)
    if plural is None:
        return None
    if isinstance(plural, str):
        raise ValueError(f"{plural_name} must be an iterable of strings")
    normalized = tuple(
        sorted({_required_text(value, singular_name) for value in plural})
    )
    if not normalized:
        raise ValueError(f"{plural_name} must not be empty")
    return normalized


def _event_query(
    selection: dict[str, object],
    *,
    replay_cutoff_sequence: int,
    ordered: bool = True,
) -> tuple[str, tuple[object, ...]]:
    clauses: list[str] = ["event.sequence <= ?"]
    parameters: list[object] = [replay_cutoff_sequence]
    start_at_ms = selection["start_at_ms"]
    end_at_ms = selection["end_at_ms"]
    session_id = selection["session_id"]
    condition_ids = selection["condition_ids"]
    market_slugs = selection["market_slugs"]
    token_id = selection["token_id"]
    if start_at_ms is not None:
        clauses.append("event.observed_at_ms >= ?")
        parameters.append(start_at_ms)
    if end_at_ms is not None:
        clauses.append("event.observed_at_ms <= ?")
        parameters.append(end_at_ms)
    if session_id is not None:
        clauses.append("event.session_id = ?")
        parameters.append(session_id)
    if condition_ids is not None:
        placeholders = ", ".join("?" for _ in condition_ids)
        clauses.append(
            f"(event.condition_id IN ({placeholders}) OR event.payload_kind = ?)"
        )
        parameters.extend((*condition_ids, PayloadKind.COVERAGE_GAP.value))
    if market_slugs is not None:
        placeholders = ", ".join("?" for _ in market_slugs)
        clauses.append(
            f"(event.market_slug IN ({placeholders}) OR event.payload_kind = ?)"
        )
        parameters.extend((*market_slugs, PayloadKind.COVERAGE_GAP.value))
    if token_id is not None:
        clauses.append(
            """
            (EXISTS (
                SELECT 1 FROM event_tokens AS selected_token
                WHERE selected_token.sequence = event.sequence
                  AND selected_token.token_id = ?
            ) OR event.payload_kind = ?)
            """
        )
        parameters.extend((token_id, PayloadKind.COVERAGE_GAP.value))
    where = "" if not clauses else "WHERE " + " AND ".join(clauses)
    order_by = " ORDER BY event.sequence" if ordered else ""
    return (
        f"SELECT event.* FROM events AS event {where}{order_by}",
        tuple(parameters),
    )


def _gap_affects(
    identity: MarketIdentity | None,
    gap: CoverageGapPayload,
    *,
    condition_ids: tuple[str, ...] | None,
    market_slugs: tuple[str, ...] | None,
    token_id: str | None,
) -> bool:
    return CoverageScope.from_gap(gap, identity).affects(
        condition_ids=condition_ids,
        market_slugs=market_slugs,
        token_id=token_id,
    )
