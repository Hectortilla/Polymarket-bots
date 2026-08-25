from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from polybot.framework.base import BaseBot
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.framework.factories import bind_bot_factory
from polybot.framework.streams import StreamRelation
from polybot_control_plane.catalog.contracts import (
    LaunchRequest,
    SelectionMode,
    WIDGET_SCHEMA_KEY,
    WidgetKind,
)
from polybot_control_plane.catalog.definitions import (
    CATALOG,
    CONTRARIAN_DEFINITION_ID,
    INITIAL_DEFINITION_VERSION,
    MARKET_WATCHER_DEFINITION_ID,
    MOMENTUM_EXAMPLE_DEFINITION_ID,
    NODE_BASED_DEFINITION_ID,
    RANDOM_HOLD_EXAMPLE_DEFINITION_ID,
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
    WINNER_DEFINITION_ID,
    catalog_descriptors,
)
from polybot_control_plane.catalog.graphs import (
    MAX_NODE_GRAPH_EDGES,
    MAX_NODE_GRAPH_NODES,
    NODE_GRAPH_COORDINATE_LIMIT,
    NODE_GRAPH_SCHEMA_VERSION,
    STARTER_NODE_GRAPH,
    GraphNodeType,
)
from polybot_control_plane.runs.contracts import PaperRunConfig


CATALOG_DEFINITION_IDS = (
    WINNER_DEFINITION_ID,
    MOMENTUM_EXAMPLE_DEFINITION_ID,
    CONTRARIAN_DEFINITION_ID,
    MARKET_WATCHER_DEFINITION_ID,
    RANDOM_HOLD_EXAMPLE_DEFINITION_ID,
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
    NODE_BASED_DEFINITION_ID,
)
WALLET = "0x0000000000000000000000000000000000000001"
PROJECT_ROOT = Path(__file__).parents[2]


def test_catalog_has_exact_initial_entries_and_generated_schemas() -> None:
    descriptors = catalog_descriptors()

    assert tuple(CATALOG) == CATALOG_DEFINITION_IDS
    assert tuple(descriptor.definition_id for descriptor in descriptors) == (
        CATALOG_DEFINITION_IDS
    )
    assert all(
        "name" in descriptor.input_schema["properties"]
        for descriptor in descriptors
    )
    assert all(
        descriptor.input_schema["properties"]["max_order_size"][
            WIDGET_SCHEMA_KEY
        ]
        == WidgetKind.DECIMAL.value
        for descriptor in descriptors
    )
    assert all("factory" not in descriptor.model_dump() for descriptor in descriptors)
    assert all(
        entry.factory.__module__ != "polybot.my_bot"
        for entry in CATALOG.values()
    )
    assert _catalog_spec_rows() == tuple(
        (
            definition_id,
            f"{entry.factory.__module__}:{entry.factory.__name__}",
            entry.market_selection.value.replace("_", "-"),
            entry.wallet_selection.value.replace("_", "-"),
            entry.label.value.replace("_", "-"),
        )
        for definition_id, entry in CATALOG.items()
    )


def test_bot_managed_definition_converts_without_selection_inputs() -> None:
    descriptor = CATALOG[WINNER_DEFINITION_ID].descriptor(WINNER_DEFINITION_ID)
    config = CATALOG[WINNER_DEFINITION_ID].parse_config({"name": "winner"})

    assert descriptor.market_selection is SelectionMode.BOT_MANAGED
    assert descriptor.wallet_selection is SelectionMode.ABSENT
    assert config.stream_rules == ()


def test_catalog_normalizes_zero_and_one_config_factories_once() -> None:
    config = BotConfig(name="factory")

    def without_config() -> BaseBot:
        return BaseBot()

    def with_config(received: BotConfig) -> BaseBot:
        assert received is config
        return BaseBot()

    template = CATALOG[WINNER_DEFINITION_ID]

    assert isinstance(replace(template, factory=without_config).create_bot(config), BaseBot)
    assert isinstance(replace(template, factory=with_config).create_bot(config), BaseBot)


def test_bot_factory_contract_rejects_invalid_signature_and_return() -> None:
    def two_arguments(first: object, second: object) -> BaseBot:
        return BaseBot()

    def wrong_return() -> object:
        return object()

    with pytest.raises(TypeError, match="zero arguments or one BotConfig"):
        bind_bot_factory(two_arguments)
    with pytest.raises(TypeError, match="did not return BaseBot"):
        bind_bot_factory(wrong_return)(BotConfig(name="factory"))


def test_wallet_definition_owns_normalized_wallet_widget_and_rule() -> None:
    entry = CATALOG[WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID]
    descriptor = entry.descriptor(WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID)
    config = entry.parse_config(
        {
            "name": "wallet-copy",
            "wallet_addresses": [WALLET.upper().replace("0X", "0x"), WALLET],
        }
    )

    wallet_schema = descriptor.input_schema["properties"]["wallet_addresses"]
    assert descriptor.wallet_selection is SelectionMode.USER_CONFIGURED
    assert wallet_schema[WIDGET_SCHEMA_KEY] == WidgetKind.WALLET_ADDRESSES.value
    assert config.stream_rules[0].relation is StreamRelation.INDEPENDENT
    assert config.stream_rules[0].wallet_addresses == (WALLET,)


def test_node_based_definition_owns_graph_widget_snapshot_and_market_rule() -> None:
    entry = CATALOG[NODE_BASED_DEFINITION_ID]
    descriptor = entry.descriptor(NODE_BASED_DEFINITION_ID)
    config = entry.parse_config(
        {"name": "node-observer", "market_slugs": [" example-market "]}
    )

    graph_schema = descriptor.input_schema["properties"]["graph"]
    assert descriptor.market_selection is SelectionMode.USER_CONFIGURED
    assert descriptor.wallet_selection is SelectionMode.ABSENT
    assert graph_schema[WIDGET_SCHEMA_KEY] == WidgetKind.NODE_GRAPH.value
    assert graph_schema["default"] == STARTER_NODE_GRAPH.model_dump(mode="json")
    assert config.graph == STARTER_NODE_GRAPH
    assert config.stream_rules[0].market_slugs == ("example-market",)
    assert type(entry.create_bot(config.to_bot_config())) is BaseBot


@pytest.mark.parametrize(
    "mutate",
    [
        lambda graph: graph["nodes"].append(graph["nodes"][0]),
        lambda graph: graph["edges"].append(graph["edges"][0]),
        lambda graph: graph["edges"][0].update(source="missing"),
        lambda graph: graph["nodes"][0].update(type="unsupported"),
        lambda graph: graph["nodes"][0].update(selected=True),
        lambda graph: graph["nodes"][0]["position"].update(
            x=NODE_GRAPH_COORDINATE_LIMIT + 1
        ),
        lambda graph: graph["nodes"][0]["position"].update(
            x=-NODE_GRAPH_COORDINATE_LIMIT - 1
        ),
        lambda graph: graph["nodes"][0]["position"].update(x=float("nan")),
        lambda graph: graph["edges"][0].update(selected=True),
        lambda graph: graph.update(viewport={"x": 0, "y": 0, "zoom": 1}),
        lambda graph: graph.update(
            schema_version=NODE_GRAPH_SCHEMA_VERSION + 1
        ),
        lambda graph: graph.update(
            nodes=[
                {**graph["nodes"][0], "id": f"node-{index}"}
                for index in range(MAX_NODE_GRAPH_NODES + 1)
            ],
            edges=[],
        ),
        lambda graph: graph.update(nodes=[]),
        lambda graph: graph.update(
            edges=[
                {**graph["edges"][0], "id": f"edge-{index}"}
                for index in range(MAX_NODE_GRAPH_EDGES + 1)
            ]
        ),
    ],
)
def test_node_graph_rejects_invalid_structure(mutate) -> None:
    graph = STARTER_NODE_GRAPH.model_dump(mode="json")
    mutate(graph)

    with pytest.raises(ValidationError):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "invalid-graph",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


def test_node_graph_uses_typed_finite_node_kinds() -> None:
    assert tuple(GraphNodeType) == (
        GraphNodeType.INPUT,
        GraphNodeType.DEFAULT,
        GraphNodeType.OUTPUT,
    )


def test_node_based_definition_rejects_blank_market_slugs_at_ingress() -> None:
    for market_slugs in (["   "], []):
        with pytest.raises(ValidationError):
            CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
                {"name": "node-observer", "market_slugs": market_slugs}
            )


def test_launch_inputs_and_request_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CATALOG[WINNER_DEFINITION_ID].parse_config(
            {"name": "winner", "private_key": "not-accepted"}
        )


@pytest.mark.parametrize("definition_id", ["", "   ", 1])
def test_launch_request_requires_a_strict_nonblank_definition_id(
    definition_id: object,
) -> None:
    with pytest.raises(ValidationError):
        LaunchRequest.model_validate(
            {
                "definition_id": definition_id,
                "definition_version": INITIAL_DEFINITION_VERSION,
                "inputs": {},
            }
        )


@pytest.mark.parametrize("definition_version", [True, 1.0, "1", 0])
def test_launch_request_requires_a_strict_positive_definition_version(
    definition_version: object,
) -> None:
    with pytest.raises(ValidationError):
        LaunchRequest.model_validate(
            {
                "definition_id": WINNER_DEFINITION_ID,
                "definition_version": definition_version,
                "inputs": {},
            }
        )

    with pytest.raises(ValidationError):
        LaunchRequest.model_validate(
            {
                "definition_id": WINNER_DEFINITION_ID,
                "definition_version": INITIAL_DEFINITION_VERSION,
                "inputs": {"name": "winner"},
                "factory": "polybot.my_bot:create",
            }
        )


def test_paper_config_preserves_decimal_strings_and_cannot_hold_credentials() -> None:
    config = CATALOG[WINNER_DEFINITION_ID].parse_config(
        {
            "name": "decimal-run",
            "max_order_size": "2.500",
            "max_slippage_pct": "0.0100",
            "paper_portfolio_usdc": "1250.00",
        }
    )
    serialized = config.model_dump(mode="json")
    bot_config = config.to_bot_config()

    assert serialized["max_order_size"] == "2.500"
    assert serialized["max_slippage_pct"] == "0.0100"
    assert serialized["paper_portfolio_usdc"] == "1250.00"
    assert config.max_order_size == Decimal("2.500")
    prohibited_fields = {
        "mode",
        "live_enabled",
        *BotConfig.sensitive_field_names(),
    }
    assert PaperRunConfig.model_fields.keys().isdisjoint(prohibited_fields)
    for field_name in prohibited_fields:
        with pytest.raises(ValidationError):
            PaperRunConfig.model_validate(
                {**serialized, field_name: "not-accepted"}
            )
    assert bot_config.mode is BotMode.PAPER
    assert bot_config.live_enabled is False
    assert all(
        getattr(bot_config, field_name) is None
        for field_name in bot_config.sensitive_field_names()
    )


def test_persisted_config_rejects_untrusted_names_and_stream_rules() -> None:
    serialized = CATALOG[WINNER_DEFINITION_ID].parse_config(
        {"name": "valid"}
    ).model_dump(mode="json")

    with pytest.raises(ValidationError):
        PaperRunConfig.model_validate({**serialized, "name": "   "})

    with pytest.raises(ValidationError):
        PaperRunConfig.model_validate(
            {
                **serialized,
                "stream_rules": [
                    {
                        "relation": StreamRelation.INDEPENDENT.value,
                        "wallet_addresses": ["not-a-wallet"],
                    }
                ],
            }
        )


def _catalog_spec_rows() -> tuple[tuple[str, ...], ...]:
    spec_path = PROJECT_ROOT / "docs" / "web-control-plane-spec.md"
    lines = spec_path.read_text().splitlines()
    header = "| Definition ID | Factory | Market | Wallet | Label |"
    first_row = lines.index(header) + 2
    table_lines = []
    for line in lines[first_row:]:
        if not line.startswith("|"):
            break
        table_lines.append(line)
    return tuple(
        tuple(cell.strip().strip("`") for cell in line.strip("|").split("|"))
        for line in table_lines
    )
