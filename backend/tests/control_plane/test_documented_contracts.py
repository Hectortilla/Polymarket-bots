"""Operator and author-facing values remain synchronized with their code owners."""

import json
import re
from pathlib import Path

from api.catalog.graphs.numbers import (
    GRAPH_NUMBER_CONTEXT,
    GRAPH_ROUND_MODE,
    MAX_NUMBER_EXPONENT,
    MAX_NUMBER_TEXT_LENGTH,
    MAX_ROUND_DECIMAL_PLACES,
)
from api.catalog.graphs.operations.logic import MAX_BOOLEAN_INPUTS, MIN_BOOLEAN_INPUTS
from api.catalog.graphs.reasons import GraphReason
from api.catalog.graphs.value_status import GraphValueStatus
from api.catalog.graphs.values import GraphOperation
from api.catalog.node_based.evaluator.diagnostics import DIAGNOSTIC_INTERVAL_MS
from api.catalog.node_based.evaluator.event_controls import MAX_STATE_KEYS_PER_NODE
from api.deployment.settings import API_PORT
from api.http.search_contracts import (
    DEFAULT_DISCOVERY_SEARCH_LIMIT,
    MAX_DISCOVERY_SEARCH_LENGTH,
    MAX_DISCOVERY_SEARCH_LIMIT,
    MIN_DISCOVERY_SEARCH_LENGTH,
    MIN_DISCOVERY_SEARCH_LIMIT,
)
from polybot.performance.contracts.sampling import DEFAULT_REPORT_INTERVAL_MS
from polybot.polymarket.discovery_policy import DISCOVERY_TIMEOUT_SECONDS


def test_documented_discovery_bounds_match_http_and_adapter_policy():
    notes = _prose("docs/api-notes.md")
    assert (
        f"query to {MIN_DISCOVERY_SEARCH_LENGTH}–{MAX_DISCOVERY_SEARCH_LENGTH} characters and result limit to {MIN_DISCOVERY_SEARCH_LIMIT}–{MAX_DISCOVERY_SEARCH_LIMIT} (default {DEFAULT_DISCOVERY_SEARCH_LIMIT})"
        in notes
    )
    assert (
        f"Both selectors have {MIN_DISCOVERY_SEARCH_LENGTH}–{MAX_DISCOVERY_SEARCH_LENGTH} character queries, at most {MAX_DISCOVERY_SEARCH_LIMIT} results (default {DEFAULT_DISCOVERY_SEARCH_LIMIT})"
        in notes
    )
    assert f"{DISCOVERY_TIMEOUT_SECONDS}-second operation timeout" in notes
    assert f"{DISCOVERY_TIMEOUT_SECONDS}-second adapter timeout" in notes


def test_documented_graph_limits_and_finite_sets_match_their_owners():
    guide = _prose("docs/graph-node-mvp.md")
    for fragment in (
        f"bounded to {MAX_NUMBER_TEXT_LENGTH} characters",
        f"adjusted decimal exponent of ±{MAX_NUMBER_EXPONENT}",
        f"{GRAPH_NUMBER_CONTEXT.prec}-significant-digit decimal context with {GRAPH_NUMBER_CONTEXT.rounding.removeprefix('ROUND_').lower().replace('_', '-')} rounding",
        f"Round uses {GRAPH_ROUND_MODE.removeprefix('ROUND_').lower().replace('_', '-')} rounding",
        f"decimal places (at most {MAX_ROUND_DECIMAL_PLACES})",
        f"AND and OR have {MIN_BOOLEAN_INPUTS}–{MAX_BOOLEAN_INPUTS} uniquely identified inputs",
        f"at most {MAX_STATE_KEYS_PER_NODE:,} keys",
        f"`{GraphReason.STATE_CAPACITY}`",
        f"at most one per {DIAGNOSTIC_INTERVAL_MS} milliseconds per node",
    ):
        assert fragment in guide
    operations = guide.split("Available operations are ", 1)[1].split(". AND", 1)[0]
    names = re.split(r", | and ", operations)
    assert {name.lower().replace(" ", "_") for name in names} == {
        item.value for item in GraphOperation
    }
    statuses = guide.split("Values carry ", 1)[1].split(" status", 1)[0]
    assert re.findall(r"`([^`]+)`", statuses) == [
        item.value for item in GraphValueStatus
    ]


def test_documented_report_interval_matches_cli_default():
    readme = _prose("README.md")
    author = _prose("docs/bot-author-guide.md")
    assert (
        f"`--report-interval-ms` defaults to `{DEFAULT_REPORT_INTERVAL_MS}`" in readme
    )
    assert f"equity samples and defaults to `{DEFAULT_REPORT_INTERVAL_MS}`" in author


def test_fixed_api_listener_matches_proxy_healthcheck_and_development_targets():
    caddy = Path("deploy/Caddyfile").read_text()
    compose = Path("deploy/compose.yaml").read_text()
    vite = Path("frontend/vite.config.ts").read_text()
    launch = json.loads(Path(".vscode/launch.json").read_text())
    api_debug = next(
        config
        for config in launch["configurations"]
        if "--port" in config.get("args", [])
    )
    assert f"reverse_proxy api:{API_PORT}" in caddy
    assert f"http://127.0.0.1:{API_PORT}/api/" in compose
    assert f'"http://127.0.0.1:{API_PORT}"' in vite
    assert api_debug["args"][api_debug["args"].index("--port") + 1] == str(API_PORT)
    assert f"control plane on port `{API_PORT}`" in _prose("README.md")


def _prose(path):
    return " ".join(Path(path).read_text().split())
