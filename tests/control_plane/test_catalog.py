from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
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
    GRAPH_CONTEXT_HANDLE_ID,
    GRAPH_NODE_CATALOG,
    MAX_NODE_GRAPH_EDGES,
    MAX_NODE_GRAPH_NODES,
    NODE_GRAPH_COORDINATE_LIMIT,
    NODE_GRAPH_SCHEMA_VERSION,
    STARTER_BOOK_OUTPUT_PATH,
    STARTER_NODE_GRAPH,
    STARTER_TRIGGER_HOOK_NAME,
    GraphFieldPath,
    GraphNodeCatalog,
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


@dataclass(frozen=True)
class NestedGraphPayloadDetails:
    price: Decimal


@dataclass(frozen=True)
class NestedGraphPayload:
    details: NestedGraphPayloadDetails


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
    assert book_fields["bids"].handle_id == "field:bids"
    assert book_fields["bids"].display_name == "BookSnapshot.bids"
    assert "bids.price" not in book_fields
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
    )


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
            {"id": "forbidden", "source": "on-book-trigger", "target": "on-book-trigger"}
        ),
        lambda graph: graph["nodes"][0].update(type="unsupported"),
        lambda graph: graph["nodes"][0].update(selected=True),
        lambda graph: graph["nodes"][0]["data"].update(hook_name="on_unknown"),
        lambda graph: graph["nodes"][0]["data"].update(
            selected_output_paths=[{"segments": ["missing"]}]
        ),
        lambda graph: graph["nodes"][0]["data"].update(
            selected_output_paths=[
                STARTER_BOOK_OUTPUT_PATH.model_dump(mode="json"),
                STARTER_BOOK_OUTPUT_PATH.model_dump(mode="json"),
            ]
        ),
        lambda graph: graph["nodes"][0]["position"].update(
            x=NODE_GRAPH_COORDINATE_LIMIT + 1
        ),
        lambda graph: graph["nodes"][0]["position"].update(
            x=-NODE_GRAPH_COORDINATE_LIMIT - 1
        ),
        lambda graph: graph["nodes"][0]["position"].update(x=float("nan")),
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
                {
                    "id": f"edge-{index}",
                    "source": "on-book-trigger",
                    "target": "on-book-trigger",
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


def test_node_graph_uses_typed_finite_node_kinds() -> None:
    assert tuple(GraphNodeType) == (GraphNodeType.TRIGGER,)
    assert STARTER_NODE_GRAPH.nodes[0].data.hook_name == STARTER_TRIGGER_HOOK_NAME
    assert STARTER_NODE_GRAPH.nodes[0].data.selected_output_paths == (
        STARTER_BOOK_OUTPUT_PATH,
    )


@pytest.mark.parametrize("hook_name", ["on_start", "on_stop"])
def test_payloadless_trigger_rejects_field_selections(hook_name: str) -> None:
    graph = STARTER_NODE_GRAPH.model_dump(mode="json")
    graph["nodes"][0]["data"] = {
        "hook_name": hook_name,
        "selected_output_paths": [GraphFieldPath(segments=("bids",)).model_dump()],
    }

    with pytest.raises(ValidationError, match="payload-less"):
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {
                "name": "invalid-lifecycle-output",
                "market_slugs": ["example-market"],
                "graph": graph,
            }
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
