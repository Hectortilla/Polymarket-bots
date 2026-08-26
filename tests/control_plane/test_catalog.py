from dataclasses import dataclass, fields, replace
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.execution.broker import Broker
from polybot.framework.events import OrderRequest, Side
from polybot.framework.factories import bind_bot_factory
from polybot.framework.graph import graph_output
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
    MARKET_WATCHER_DEFINITION_ID,
    MOMENTUM_EXAMPLE_DEFINITION_ID,
    NODE_BASED_DEFINITION_ID,
    RANDOM_HOLD_EXAMPLE_DEFINITION_ID,
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
    WINNER_DEFINITION_ID,
    catalog_descriptors,
)
from polybot_control_plane.catalog.graphs.catalog import (
    GRAPH_NODE_CATALOG,
    GraphNodeCatalog,
)
from polybot_control_plane.catalog.graphs.contracts import (
    MAX_NODE_GRAPH_EDGES,
    MAX_NODE_GRAPH_NODES,
    GraphBooleanConstantData,
    GraphDecimalConstantData,
    GraphIntegerConstantData,
    GraphStringConstantData,
    NodeGraph,
)
from polybot_control_plane.catalog.graphs.starter import (
    STARTER_NODE_GRAPH,
    STARTER_TRIGGER_HOOK_NAME,
    STARTER_TRIGGER_NODE_ID,
)
from polybot_control_plane.catalog.graphs.types import (
    GRAPH_ACTION_ENABLED_HANDLE_ID,
    GRAPH_COMPARISON_LEFT_HANDLE_ID,
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GRAPH_COMPARISON_RIGHT_HANDLE_ID,
    GRAPH_CONTEXT_HANDLE_ID,
    GRAPH_VALUE_HANDLE_ID,
    NODE_GRAPH_COORDINATE_LIMIT,
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphFieldPath,
    GraphNodeType,
    GraphScalarType,
)
from polybot_control_plane.runs.contracts import PaperRunConfig
from control_plane.graph_catalog_fixture import (
    FRONTEND_FIXTURE_PATH,
    frontend_graph_catalog,
)
from control_plane.graph_fixtures import threshold_buy_graph


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


@dataclass(frozen=True)
class NestedGraphPayloadDetails:
    price: Decimal


@dataclass(frozen=True)
class NestedGraphPayload:
    details: NestedGraphPayloadDetails

    @property
    @graph_output
    def computed(self) -> NestedGraphPayloadDetails | None:
        return self.details

    @property
    def hidden(self) -> NestedGraphPayloadDetails:
        return self.details


class NestedPayloadBot:
    async def on_nested(
        self,
        ctx: BotContext,
        payload: NestedGraphPayload,
    ) -> None:
        pass


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
        (descriptor.graph_catalog is not None)
        == (descriptor.definition_id == NODE_BASED_DEFINITION_ID)
        for descriptor in descriptors
    )
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
    assert descriptor.graph_catalog == GRAPH_NODE_CATALOG
    assert config.graph == STARTER_NODE_GRAPH
    assert config.stream_rules[0].market_slugs == ("example-market",)
    assert type(entry.create_bot(config.to_bot_config())) is BaseBot


def test_graph_catalog_derives_base_bot_lifecycle_hooks_and_payload_fields() -> None:
    triggers = GRAPH_NODE_CATALOG.triggers
    trigger_names = tuple(trigger.hook_name for trigger in triggers)

    assert trigger_names == (
        "on_start",
        "on_book",
        "on_book_gap",
        "on_wallet_trade",
        "on_fill",
        "on_market_resolved",
        "on_stop",
    )
    assert "current_stream_rules" not in trigger_names
    assert "next_stream_rules" not in trigger_names
    assert "backtest_is_quiescent" not in trigger_names
    assert all(
        trigger.context_handle_id == GRAPH_CONTEXT_HANDLE_ID
        and trigger.context_type_name == BotContext.__name__
        for trigger in triggers
    )

    book = GRAPH_NODE_CATALOG.trigger("on_book")
    wallet_trade = GRAPH_NODE_CATALOG.trigger("on_wallet_trade")
    assert book is not None and book.payload is not None
    assert wallet_trade is not None and wallet_trade.payload is not None
    book_fields = {field.path.dotted: field for field in book.payload.fields}
    wallet_fields = {field.path.dotted: field for field in wallet_trade.payload.fields}
    assert book_fields["bids"].collection is True
    assert book_fields["bids"].value_type == "BookLevel"
    assert book_fields["bids"].handle_id == GraphFieldPath(
        segments=("bids",)
    ).handle_id
    assert book_fields["bids"].display_name == "BookSnapshot.bids"
    assert "bids.price" not in book_fields
    assert {
        path for path in book_fields if path.startswith("best_")
    } == {
        "best_bid.price",
        "best_bid.size",
        "best_ask.price",
        "best_ask.size",
    }
    assert all(
        book_fields[path].scalar_type is GraphScalarType.DECIMAL
        and book_fields[path].nullable
        for path in (
            "best_bid.price",
            "best_bid.size",
            "best_ask.price",
            "best_ask.size",
        )
    )
    assert "midpoint" not in book_fields
    assert wallet_fields["size"].value_type == "Decimal"
    assert "source_key" not in wallet_fields
    on_start = GRAPH_NODE_CATALOG.trigger("on_start")
    on_stop = GRAPH_NODE_CATALOG.trigger("on_stop")
    assert on_start is not None and on_start.payload is None
    assert on_stop is not None and on_stop.payload is None


@pytest.mark.parametrize(
    ("hook_name", "expected_fields"),
    [
        (
            "on_book",
            (
                ("token_id", "str", False, False),
                ("bids", "BookLevel", False, True),
                ("asks", "BookLevel", False, True),
                ("received_at_ms", "int", False, False),
                ("market_slug", "str", True, False),
                ("condition_id", "str", True, False),
                ("outcome", "str", True, False),
                ("best_bid.price", "Decimal", True, False),
                ("best_bid.size", "Decimal", True, False),
                ("best_ask.price", "Decimal", True, False),
                ("best_ask.size", "Decimal", True, False),
            ),
        ),
        (
            "on_book_gap",
            (
                ("condition_id", "str", True, False),
                ("observed_at_ms", "int", False, False),
                ("reason", "BookGapReason", False, False),
            ),
        ),
        (
            "on_wallet_trade",
            (
                ("wallet", "str", False, False),
                ("condition_id", "str", False, False),
                ("token_id", "str", False, False),
                ("side", "Side", False, False),
                ("size", "Decimal", False, False),
                ("price", "Decimal", False, False),
                ("source_id", "str", False, False),
                ("trade_timestamp_ms", "int", False, False),
                ("observed_at_ms", "int", False, False),
                ("kind", "WalletTradeKind", False, False),
                ("market_slug", "str", True, False),
                ("transaction_hash", "str", True, False),
                ("outcome", "str", True, False),
            ),
        ),
        (
            "on_fill",
            (
                ("order_id", "str", False, False),
                ("token_id", "str", False, False),
                ("side", "Side", False, False),
                ("status", "OrderStatus", False, False),
                ("requested_size", "Decimal", False, False),
                ("filled_size", "Decimal", False, False),
                ("average_price", "Decimal", True, False),
                ("fee_usdc", "Decimal", False, False),
                ("received_at_ms", "int", False, False),
                ("reject_reason", "FillRejectReason", True, False),
                ("reject_message", "str", True, False),
            ),
        ),
        (
            "on_market_resolved",
            (
                ("condition_id", "str", False, False),
                ("market_slug", "str", False, False),
                ("token_ids", "str", False, True),
                ("winning_token_id", "str", False, False),
                ("winning_outcome", "str", False, False),
                ("resolved_at_ms", "int", False, False),
                ("source", "str", False, False),
            ),
        ),
    ],
)
def test_graph_catalog_derives_exact_payload_fields(
    hook_name: str,
    expected_fields: tuple[tuple[str, str, bool, bool], ...],
) -> None:
    trigger = GRAPH_NODE_CATALOG.trigger(hook_name)

    assert trigger is not None and trigger.payload is not None
    assert tuple(
        (field.path.dotted, field.value_type, field.nullable, field.collection)
        for field in trigger.payload.fields
    ) == expected_fields


def test_graph_catalog_preserves_enum_schema() -> None:
    trigger = GRAPH_NODE_CATALOG.trigger("on_wallet_trade")

    assert trigger is not None and trigger.payload is not None
    side = trigger.payload.field_for_path(GraphFieldPath(segments=("side",)))
    assert side is not None
    assert side.value_schema["enum"] == ["BUY", "SELL"]


def test_graph_catalog_recurses_through_nested_dataclasses() -> None:
    catalog = GraphNodeCatalog.from_bot_type(NestedPayloadBot)
    trigger = catalog.trigger("on_nested")

    assert trigger is not None and trigger.payload is not None
    assert tuple(field.path.dotted for field in trigger.payload.fields) == (
        "details",
        "details.price",
        "computed.price",
    )
    computed = trigger.payload.field_for_path(
        GraphFieldPath(segments=("computed", "price"))
    )
    assert computed is not None and computed.nullable


def test_graph_catalog_rejects_unsupported_trigger_signatures() -> None:
    class InvalidBot:
        async def on_invalid(
            self,
            ctx: BotContext,
            first: object,
            second: object,
        ) -> None:
            pass

    with pytest.raises(TypeError, match="at most one payload"):
        GraphNodeCatalog.from_bot_type(InvalidBot)

    class InvalidPayloadBot:
        async def on_invalid(self, ctx: BotContext, payload: int) -> None:
            pass

    with pytest.raises(TypeError, match="dataclass"):
        GraphNodeCatalog.from_bot_type(InvalidPayloadBot)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda graph: graph["nodes"].append(graph["nodes"][0]),
        lambda graph: graph["nodes"].append(
            {
                **graph["nodes"][0],
                "id": "duplicate-hook",
                "position": {"x": 200, "y": 80},
            }
        ),
        lambda graph: graph["edges"].append(
            {
                "id": "forbidden",
                "source": STARTER_TRIGGER_NODE_ID,
                "target": STARTER_TRIGGER_NODE_ID,
            }
        ),
        lambda graph: graph["nodes"][0].update(type="unsupported"),
        lambda graph: graph["nodes"][0].update(selected=True),
        lambda graph: graph["nodes"][0]["data"].update(hook_name="on_unknown"),
        lambda graph: graph["nodes"][0]["data"].update(
            selected_output_paths=[{"segments": ["bids"]}]
        ),
        lambda graph: graph["nodes"][0]["position"].update(
            x=NODE_GRAPH_COORDINATE_LIMIT + 1
        ),
        lambda graph: graph["nodes"][0]["position"].update(
            x=-NODE_GRAPH_COORDINATE_LIMIT - 1
        ),
        lambda graph: graph["nodes"][0]["position"].update(x=float("nan")),
        lambda graph: graph.update(viewport={"x": 0, "y": 0, "zoom": 1}),
        lambda graph: graph.update(schema_version=1),
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
                {
                    "id": f"edge-{index}",
                    "source": STARTER_TRIGGER_NODE_ID,
                    "source_handle": GRAPH_VALUE_HANDLE_ID,
                    "target": STARTER_TRIGGER_NODE_ID,
                    "target_handle": GRAPH_CONTEXT_HANDLE_ID,
                }
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


def test_node_graph_enforces_the_edge_limit_before_semantic_validation() -> None:
    graph = STARTER_NODE_GRAPH.model_dump(mode="json")
    graph["edges"] = [
        {
            "id": f"edge-{index}",
            "source": STARTER_TRIGGER_NODE_ID,
            "source_handle": GRAPH_VALUE_HANDLE_ID,
            "target": STARTER_TRIGGER_NODE_ID,
            "target_handle": GRAPH_CONTEXT_HANDLE_ID,
        }
        for index in range(MAX_NODE_GRAPH_EDGES + 1)
    ]

    with pytest.raises(ValidationError) as error:
        NodeGraph.model_validate(graph)

    assert any(
        detail["loc"] == ("edges",) and detail["type"] == "too_long"
        for detail in error.value.errors()
    )


def test_node_graph_enforces_the_node_limit_before_semantic_validation() -> None:
    graph = {
        "nodes": [
            {
                "id": f"constant-{index}",
                "type": GraphNodeType.CONSTANT,
                "position": {"x": 0, "y": 0},
                "data": {
                    "scalar_type": GraphScalarType.STRING,
                    "value": str(index),
                },
            }
            for index in range(MAX_NODE_GRAPH_NODES + 1)
        ],
        "edges": [],
    }

    with pytest.raises(ValidationError) as error:
        NodeGraph.model_validate(graph)

    assert any(
        detail["loc"] == ("nodes",) and detail["type"] == "too_long"
        for detail in error.value.errors()
    )


def test_node_graph_uses_typed_finite_node_kinds() -> None:
    assert tuple(GraphNodeType) == (
        GraphNodeType.TRIGGER,
        GraphNodeType.CONSTANT,
        GraphNodeType.COMPARISON,
        GraphNodeType.BROKER_ACTION,
    )
    assert STARTER_NODE_GRAPH.nodes[0].data.hook_name == STARTER_TRIGGER_HOOK_NAME
    assert STARTER_NODE_GRAPH.nodes[0].data.model_dump() == {
        "hook_name": STARTER_TRIGGER_HOOK_NAME
    }


def test_graph_catalog_describes_constants_comparisons_and_submit_actions() -> None:
    assert tuple(item.scalar_type for item in GRAPH_NODE_CATALOG.constants) == tuple(
        GraphScalarType
    )
    assert tuple(item.operator for item in GRAPH_NODE_CATALOG.comparisons) == tuple(
        GraphComparisonOperator
    )
    for comparison in GRAPH_NODE_CATALOG.comparisons:
        expected_scalar_types = (
            tuple(GraphScalarType)
            if comparison.operator
            in {GraphComparisonOperator.EQUAL, GraphComparisonOperator.NOT_EQUAL}
            else (GraphScalarType.INTEGER, GraphScalarType.DECIMAL)
        )
        assert all(
            input_.scalar_types == expected_scalar_types
            and input_.required
            and input_.nullable
            for input_ in comparison.inputs
        )
        assert comparison.output.scalar_type is GraphScalarType.BOOLEAN
    assert tuple(item.action for item in GRAPH_NODE_CATALOG.broker_actions) == tuple(
        GraphBrokerAction
    )
    assert tuple(item.side for item in GRAPH_NODE_CATALOG.broker_actions) == tuple(Side)
    order_input_names = tuple(
        field.name for field in fields(OrderRequest) if field.name != "side"
    )
    assert all(
        action.method_name == Broker.submit.__name__
        and tuple(input_.handle_id for input_ in action.inputs)
        == (GRAPH_ACTION_ENABLED_HANDLE_ID, *order_input_names)
        for action in GRAPH_NODE_CATALOG.broker_actions
    )
    assert all(
        input_.required and not input_.nullable
        for input_ in GRAPH_NODE_CATALOG.broker_actions[0].inputs[:4]
    )
    assert all(
        not input_.required and input_.nullable
        for input_ in GRAPH_NODE_CATALOG.broker_actions[0].inputs[4:]
    )
    assert Broker.cancel_all.__name__ not in {
        action.method_name for action in GRAPH_NODE_CATALOG.broker_actions
    }


def test_frontend_graph_catalog_fixture_matches_backend_contract() -> None:
    assert json.loads(FRONTEND_FIXTURE_PATH.read_text(encoding="utf-8")) == (
        frontend_graph_catalog()
    )


def test_threshold_buy_graph_validates_and_preserves_exact_decimals() -> None:
    graph = threshold_buy_graph()

    config = CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
        {
            "name": "threshold-buy",
            "market_slugs": ["example-market"],
            "graph": graph,
        }
    )

    assert config.graph is not None
    serialized = config.graph.model_dump(mode="json")
    constants = {
        node["id"]: node["data"]["value"]
        for node in serialized["nodes"]
        if node["type"] == GraphNodeType.CONSTANT
    }
    assert constants == {
        "constant-threshold": "0.5500",
        "constant-size": "1.250",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda graph: graph["edges"].pop(),
        lambda graph: graph["edges"].pop(0),
        lambda graph: graph["edges"][0].update(source_handle="field:token_id"),
        lambda graph: graph["edges"][0].update(source_handle="field:unselected"),
        lambda graph: graph["edges"][0].update(
            source="action-buy",
            source_handle=GRAPH_VALUE_HANDLE_ID,
        ),
        lambda graph: graph["edges"][0].update(target_handle="missing"),
        lambda graph: graph["edges"][0].update(
            target=STARTER_TRIGGER_NODE_ID,
            target_handle=GRAPH_CONTEXT_HANDLE_ID,
        ),
        lambda graph: graph["edges"].append(
            {
                **graph["edges"][-1],
                "id": "duplicate-size-input",
            }
        ),
        lambda graph: graph["edges"][1].update(id=graph["edges"][0]["id"]),
        lambda graph: graph["edges"][0].update(source="missing-node"),
        lambda graph: graph["edges"][0].update(target="missing-node"),
        lambda graph: graph["nodes"].append(
            {
                "id": "disconnected-constant",
                "type": "constant",
                "position": {"x": 0, "y": 0},
                "data": {"scalar_type": "string", "value": "unused"},
            }
        ),
    ],
)
def test_functional_graph_rejects_invalid_handles_types_cardinality_and_disconnects(
    mutate,
) -> None:
    graph = threshold_buy_graph()
    mutate(graph)

    with pytest.raises(ValidationError):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "invalid-functional-graph",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


def test_functional_graph_rejects_cross_trigger_joins() -> None:
    graph = threshold_buy_graph()
    graph["nodes"].append(
        {
            "id": "wallet-trigger",
            "type": "trigger",
            "position": {"x": 0, "y": 500},
            "data": {"hook_name": "on_wallet_trade"},
        }
    )
    graph["edges"][1].update(
        source="wallet-trigger",
        source_handle=GraphFieldPath(segments=("price",)).handle_id,
    )

    with pytest.raises(ValidationError, match="one trigger branch"):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "cross-trigger",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


def test_functional_graph_rejects_mixed_comparison_scalar_types() -> None:
    graph = threshold_buy_graph()
    graph["nodes"][1]["data"] = {
        "scalar_type": GraphScalarType.INTEGER.value,
        "value": 1,
    }

    with pytest.raises(ValidationError, match="matching scalar input types"):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "mixed-comparison-types",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


def test_functional_graph_rejects_collection_sources() -> None:
    graph = threshold_buy_graph()
    graph["edges"][0]["source_handle"] = GraphFieldPath(
        segments=("bids",)
    ).handle_id

    with pytest.raises(ValidationError, match="scalar trigger output"):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "collection-source",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


def test_functional_graph_rejects_multiple_action_trigger_ancestors() -> None:
    graph = threshold_buy_graph()
    graph["nodes"].append(
        {
            "id": "wallet-trigger",
            "type": GraphNodeType.TRIGGER.value,
            "position": {"x": 0, "y": 500},
            "data": {"hook_name": "on_wallet_trade"},
        }
    )
    graph["edges"][3].update(
        source="wallet-trigger",
        source_handle=GraphFieldPath(segments=("token_id",)).handle_id,
    )

    with pytest.raises(ValidationError, match="one trigger branch"):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "multi-trigger-action",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


def test_functional_graph_rejects_action_without_trigger_ancestry() -> None:
    graph = threshold_buy_graph()
    action = graph["nodes"][4]
    graph["nodes"] = [
        graph["nodes"][1],
        graph["nodes"][2],
        {
            "id": "constant-enabled",
            "type": GraphNodeType.CONSTANT.value,
            "position": {"x": 0, "y": 400},
            "data": {"scalar_type": GraphScalarType.BOOLEAN.value, "value": True},
        },
        {
            "id": "constant-token",
            "type": GraphNodeType.CONSTANT.value,
            "position": {"x": 0, "y": 500},
            "data": {"scalar_type": GraphScalarType.STRING.value, "value": "token"},
        },
        action,
    ]
    graph["edges"] = [
        {
            "id": edge_id,
            "source": source,
            "source_handle": GRAPH_VALUE_HANDLE_ID,
            "target": "action-buy",
            "target_handle": target_handle,
        }
        for edge_id, source, target_handle in (
            ("enabled", "constant-enabled", GRAPH_ACTION_ENABLED_HANDLE_ID),
            ("token", "constant-token", "token_id"),
            ("price", "constant-threshold", "price"),
            ("size", "constant-size", "size"),
        )
    ]

    with pytest.raises(ValidationError, match="one trigger branch"):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "triggerless-action",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


@pytest.mark.parametrize(
    ("model", "scalar_type", "value"),
    [
        (GraphBooleanConstantData, GraphScalarType.BOOLEAN, "true"),
        (GraphIntegerConstantData, GraphScalarType.INTEGER, True),
        (GraphDecimalConstantData, GraphScalarType.DECIMAL, "NaN"),
        (GraphDecimalConstantData, GraphScalarType.DECIMAL, "Infinity"),
        (GraphDecimalConstantData, GraphScalarType.DECIMAL, "not-decimal"),
        (GraphStringConstantData, GraphScalarType.STRING, 1),
    ],
)
def test_constant_data_rejects_coercion_and_nonfinite_decimals(
    model,
    scalar_type: GraphScalarType,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"scalar_type": scalar_type, "value": value})


def test_functional_graph_rejects_cycles() -> None:
    graph = _cyclic_graph()

    with pytest.raises(ValidationError, match="acyclic"):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "cycle",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


@pytest.mark.parametrize("hook_name", ["on_start", "on_book"])
def test_trigger_rejects_legacy_output_selections(hook_name: str) -> None:
    graph = STARTER_NODE_GRAPH.model_dump(mode="json")
    graph["nodes"][0]["data"] = {
        "hook_name": hook_name,
        "selected_output_paths": [GraphFieldPath(segments=("bids",)).model_dump()],
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "invalid-lifecycle-output",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
        )


def test_payloadless_trigger_graph_accepts_hook_only_data() -> None:
    graph = STARTER_NODE_GRAPH.model_dump(mode="json")
    graph["nodes"][0]["data"] = {
        "hook_name": "on_start",
    }

    config = CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
        {
            "name": "start-trigger",
            "market_slugs": ["example-market"],
            "graph": graph,
        }
    )

    assert config.graph is not None
    assert config.graph.nodes[0].data.hook_name == "on_start"


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
                "inputs": {},
            }
        )


def test_launch_request_has_no_definition_version_or_factory_fields() -> None:
    with pytest.raises(ValidationError):
        LaunchRequest.model_validate(
            {
                "definition_id": WINNER_DEFINITION_ID,
                "definition_version": 1,
                "inputs": {},
            }
        )

    with pytest.raises(ValidationError):
        LaunchRequest.model_validate(
            {
                "definition_id": WINNER_DEFINITION_ID,
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


def _cyclic_graph() -> dict[str, object]:
    graph = threshold_buy_graph()
    graph["nodes"] = [
        graph["nodes"][0],
        graph["nodes"][2],
        {
            "id": "boolean-one",
            "type": GraphNodeType.CONSTANT.value,
            "position": {"x": 0, "y": 300},
            "data": {"scalar_type": GraphScalarType.BOOLEAN.value, "value": True},
        },
        {
            "id": "boolean-two",
            "type": GraphNodeType.CONSTANT.value,
            "position": {"x": 0, "y": 400},
            "data": {
                "scalar_type": GraphScalarType.BOOLEAN.value,
                "value": False,
            },
        },
        {
            "id": "comparison-one",
            "type": GraphNodeType.COMPARISON.value,
            "position": {"x": 250, "y": 100},
            "data": {"operator": GraphComparisonOperator.EQUAL.value},
        },
        {
            "id": "comparison-two",
            "type": GraphNodeType.COMPARISON.value,
            "position": {"x": 250, "y": 200},
            "data": {"operator": GraphComparisonOperator.EQUAL.value},
        },
        graph["nodes"][4],
    ]
    edge_specs = (
        (
            "one-left",
            "comparison-two",
            GRAPH_COMPARISON_RESULT_HANDLE_ID,
            "comparison-one",
            GRAPH_COMPARISON_LEFT_HANDLE_ID,
        ),
        (
            "one-right",
            "boolean-one",
            GRAPH_VALUE_HANDLE_ID,
            "comparison-one",
            GRAPH_COMPARISON_RIGHT_HANDLE_ID,
        ),
        (
            "two-left",
            "comparison-one",
            GRAPH_COMPARISON_RESULT_HANDLE_ID,
            "comparison-two",
            GRAPH_COMPARISON_LEFT_HANDLE_ID,
        ),
        (
            "two-right",
            "boolean-two",
            GRAPH_VALUE_HANDLE_ID,
            "comparison-two",
            GRAPH_COMPARISON_RIGHT_HANDLE_ID,
        ),
        (
            "enabled",
            "comparison-one",
            GRAPH_COMPARISON_RESULT_HANDLE_ID,
            "action-buy",
            GRAPH_ACTION_ENABLED_HANDLE_ID,
        ),
        (
            "token",
            "on-book-trigger",
            GraphFieldPath(segments=("token_id",)).handle_id,
            "action-buy",
            "token_id",
        ),
        (
            "price",
            "on-book-trigger",
            GraphFieldPath(segments=("best_ask", "price")).handle_id,
            "action-buy",
            "price",
        ),
        ("size", "constant-size", GRAPH_VALUE_HANDLE_ID, "action-buy", "size"),
    )
    graph["edges"] = [
        {
            "id": edge_id,
            "source": source,
            "source_handle": source_handle,
            "target": target,
            "target_handle": target_handle,
        }
        for edge_id, source, source_handle, target, target_handle in edge_specs
    ]
    return graph
