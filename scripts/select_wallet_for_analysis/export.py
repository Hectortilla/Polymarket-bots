from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from polybot.framework.wallets import normalize_wallet_address
from scripts.polymarket_wallet_api import fetch_all_activity, fetch_gamma_market
from scripts.polymarket_wallet_api.constants import (
    MARKET_ACTIVE_FIELD,
    MARKET_CLOSED_FIELD,
    MARKET_END_DATE_FIELD,
    MARKET_OUTCOMES_FIELD,
    MARKET_QUESTION_FIELD,
    MARKET_START_DATE_FIELD,
    MARKET_WINNING_OUTCOME_FIELD,
)
from scripts.wallet_payload_contracts import ACTIVITY_SLUG_FIELD, CONDITION_ID_FIELD, ActivityRow
from scripts.paths import RESULTS_DIR

DATA_FILENAME_TEMPLATE = "data_{wallet_id}.json"


def export_activity(wallet: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    activity, truncated = fetch_all_activity(wallet)
    contexts = _market_context_from_activity(activity)
    payload = {
        "wallet": wallet,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "truncated": truncated,
        "activity": [_enrich_activity_row(row, contexts) for row in activity],
        "market_context": list(contexts.values()),
    }
    path = RESULTS_DIR / DATA_FILENAME_TEMPLATE.format(
        wallet_id=normalize_wallet_address(wallet)
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _market_context_from_activity(
    activity: list[ActivityRow],
) -> dict[str, dict[str, object]]:
    contexts = {}
    for row in activity:
        condition_id = row.get(CONDITION_ID_FIELD)
        if isinstance(condition_id, str) and condition_id not in contexts:
            contexts[condition_id] = _fetch_market_context(condition_id)
    return contexts


def _fetch_market_context(condition_id: str) -> dict[str, object]:
    market = fetch_gamma_market(condition_id)
    if market is None:
        return {"condition_id": condition_id}
    return {
        "condition_id": market.get(CONDITION_ID_FIELD) or condition_id,
        "market_slug": market.get(ACTIVITY_SLUG_FIELD),
        "market_name": market.get(MARKET_QUESTION_FIELD) or market.get(
            ACTIVITY_SLUG_FIELD
        ),
        "market_start_timestamp": _timestamp(market.get(MARKET_START_DATE_FIELD)),
        "market_end_timestamp": _timestamp(market.get(MARKET_END_DATE_FIELD)),
        "market_active": market.get(MARKET_ACTIVE_FIELD),
        "market_closed": market.get(MARKET_CLOSED_FIELD),
        "market_resolved_outcome": market.get(MARKET_WINNING_OUTCOME_FIELD),
        "market_outcomes": market.get(MARKET_OUTCOMES_FIELD),
    }


def _timestamp(value: object) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return None


def _enrich_activity_row(
    row: ActivityRow,
    contexts: dict[str, dict[str, object]],
) -> dict[str, object]:
    enriched = dict(row)
    condition_id = row.get(CONDITION_ID_FIELD)
    if isinstance(condition_id, str) and condition_id in contexts:
        enriched.update(contexts[condition_id])
        enriched["market_context"] = contexts[condition_id]
    timestamp = row.get("timestamp")
    if timestamp is not None:
        enriched["timestamp_ms"] = timestamp * 1000
        start = enriched.get("market_start_timestamp")
        if isinstance(start, int):
            enriched["market_offset_seconds"] = timestamp - start
    return enriched
