"""Backend-evaluated semantic cases for the browser's live ingress contract."""

import json
from datetime import UTC, datetime
from uuid import UUID

from api.events.contracts import LiveRunSnapshot
from api.events.contracts.payloads.base import MAX_JSON_INTEGER
from api.events.contracts.payloads.chart import (
    EquityChartPointPayload,
    MarketChartPointPayload,
)
from api.events.contracts.payloads.lifecycle import FeedObservation
from polybot.cli.observability.events import StreamHealth
from polybot.framework.events import Side
from polybot.performance.contracts.valuation_status import ValuationStatus
from pydantic import ValidationError


def live_validation_cases():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    payload = LiveRunSnapshot(
        run_id=UUID(int=1),
        occurred_at=now,
        generation=1,
        sequence=1,
        sampled_at_ms=1,
        markets=(
            MarketChartPointPayload(
                token_id="token",
                label="Market",
                value="0.5",
                status=ValuationStatus.FRESH,
                markers=(),
            ),
        ),
        equity=EquityChartPointPayload(value="100", status=ValuationStatus.FRESH),
        health=FeedObservation.from_observation(StreamHealth(0, 0, 0), observed_at=now),
    ).model_dump(mode="json")
    point = payload["markets"][0]
    candidates = {
        "valid": payload,
        "markers": payload | {"markets": [point | {"markers": [Side.BUY]}]},
        "duplicate tokens": payload | {"markets": [point, point]},
        "blank token": payload | {"markets": [point | {"token_id": " "}]},
        "blank label": payload | {"markets": [point | {"label": " "}]},
        "unsafe sample time": payload | {"sampled_at_ms": MAX_JSON_INTEGER + 1},
        "unsafe health counter": payload
        | {
            "health": payload["health"]
            | {
                "health": payload["health"]["health"]
                | {"queue_depth": MAX_JSON_INTEGER + 1}
            }
        },
        "unsafe sequence": payload | {"sequence": MAX_JSON_INTEGER + 1},
    }
    cases = []
    for name, value in candidates.items():
        try:
            LiveRunSnapshot.model_validate_json(json.dumps(value), strict=True)
            accepted = True
        except ValidationError:
            accepted = False
        cases.append({"name": name, "payload": value, "accepted": accepted})
    return cases
