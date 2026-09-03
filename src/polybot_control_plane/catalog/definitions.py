"""Initial trusted bot definitions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast

from polybot.examples.btc_5m import create as create_market_watcher
from polybot.examples.example_btc_five_minute_momentum import (
    create as create_momentum_example,
)
from polybot.examples.example_dynamic_random_hold import (
    create as create_random_hold_example,
)
from polybot.examples.example_dynamic_random_hold_wallet_filter_copy import (
    create as create_wallet_filter_copy_example,
)
from polybot.examples.meh_trading_bot import create as create_contrarian
from polybot.examples.winner_trading_bot import create as create_winner
from polybot.framework.base import BaseBot
from polybot.framework.factories import BoundBotFactory, bind_bot_factory
from polybot.framework.config.models import BotConfig
from polybot_control_plane.catalog.contracts import BotDefinitionDescriptor
from polybot_control_plane.catalog.values import (
    BotDefinitionLabel,
    DefinitionId,
    SelectionMode,
)
from polybot_control_plane.catalog.graphs.catalog import (
    GRAPH_NODE_CATALOG,
    GraphNodeCatalog,
)
from polybot_control_plane.catalog.inputs import (
    ContrarianLaunchInputs,
    MarketWatcherLaunchInputs,
    MomentumExampleLaunchInputs,
    NodeBasedLaunchInputs,
    PaperLaunchInputs,
    RandomHoldExampleLaunchInputs,
    WalletFilterCopyExampleLaunchInputs,
    WinnerLaunchInputs,
)
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.catalog.graphs.starter import STARTER_NODE_GRAPH
from polybot_control_plane.catalog.node_based.bot import NodeBasedBot
from polybot_control_plane.runs.contracts import PaperRunConfig

WINNER_DEFINITION_ID = "btc-five-minute-winner"
MOMENTUM_EXAMPLE_DEFINITION_ID = "btc-five-minute-momentum-example"
CONTRARIAN_DEFINITION_ID = "btc-five-minute-contrarian"
MARKET_WATCHER_DEFINITION_ID = "btc-five-minute-market-watcher"
RANDOM_HOLD_EXAMPLE_DEFINITION_ID = "dynamic-random-hold-example"
WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID = "dynamic-wallet-filter-copy-example"
NODE_BASED_DEFINITION_ID = "node-based-bot"


GraphValue = TypeVar("GraphValue")


class GraphRequirementError(ValueError):
    def __init__(self, *, graph_required: bool) -> None:
        self.graph_required = graph_required
        message = "graph is required" if graph_required else "graph is forbidden"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GraphCapability:
    catalog: GraphNodeCatalog
    starter_graph: NodeGraph
    factory: Callable[[NodeGraph], BaseBot]


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    display_name: str
    description: str
    label: BotDefinitionLabel
    market_selection: SelectionMode
    wallet_selection: SelectionMode
    launch_model: type[PaperLaunchInputs]
    factory: BoundBotFactory | None = None
    graph_capability: GraphCapability | None = None

    def __post_init__(self) -> None:
        if (self.factory is None) == (self.graph_capability is None):
            raise ValueError(
                "catalog entries require exactly one ordinary or graph bot factory"
            )

    def descriptor(self, definition_id: DefinitionId) -> BotDefinitionDescriptor:
        return BotDefinitionDescriptor(
            definition_id=definition_id,
            display_name=self.display_name,
            description=self.description,
            label=self.label,
            market_selection=self.market_selection,
            wallet_selection=self.wallet_selection,
            input_schema=self.launch_model.model_json_schema(),
            graph_catalog=(
                None if self.graph_capability is None else self.graph_capability.catalog
            ),
            starter_graph=(
                None
                if self.graph_capability is None
                else self.graph_capability.starter_graph
            ),
        )

    def parse_config(self, inputs: object) -> PaperRunConfig:
        return self.launch_model.model_validate(inputs).to_run_config()

    @property
    def requires_graph(self) -> bool:
        return self.graph_capability is not None

    def require_graph_value(
        self,
        graph_value: GraphValue | None,
    ) -> GraphValue | None:
        if self.requires_graph and graph_value is None:
            raise GraphRequirementError(graph_required=True)
        if not self.requires_graph and graph_value is not None:
            raise GraphRequirementError(graph_required=False)
        return graph_value

    def create_bot(
        self,
        config: BotConfig,
        graph: NodeGraph | None = None,
    ) -> BaseBot:
        graph = self.require_graph_value(graph)
        if self.graph_capability is not None:
            return self.graph_capability.factory(cast(NodeGraph, graph))
        assert self.factory is not None
        return self.factory(config)


CATALOG: dict[str, CatalogEntry] = {
    WINNER_DEFINITION_ID: CatalogEntry(
        display_name="BTC five-minute winner",
        description="Trades a strong late leader in consecutive BTC markets.",
        label=BotDefinitionLabel.STANDARD,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=WinnerLaunchInputs,
        factory=bind_bot_factory(create_winner),
    ),
    MOMENTUM_EXAMPLE_DEFINITION_ID: CatalogEntry(
        display_name="BTC five-minute momentum example",
        description="Example strategy driven by paired outcome-book momentum.",
        label=BotDefinitionLabel.EXAMPLE,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=MomentumExampleLaunchInputs,
        factory=bind_bot_factory(create_momentum_example),
    ),
    CONTRARIAN_DEFINITION_ID: CatalogEntry(
        display_name="BTC five-minute contrarian",
        description="Trades a selective late reversal in consecutive BTC markets.",
        label=BotDefinitionLabel.STANDARD,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=ContrarianLaunchInputs,
        factory=bind_bot_factory(create_contrarian),
    ),
    MARKET_WATCHER_DEFINITION_ID: CatalogEntry(
        display_name="BTC five-minute market watcher",
        description="Observes consecutive BTC markets without trading.",
        label=BotDefinitionLabel.NON_TRADING,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=MarketWatcherLaunchInputs,
        factory=bind_bot_factory(create_market_watcher),
    ),
    RANDOM_HOLD_EXAMPLE_DEFINITION_ID: CatalogEntry(
        display_name="Dynamic random-hold example",
        description="Example random-hold strategy for consecutive BTC markets.",
        label=BotDefinitionLabel.EXAMPLE,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=RandomHoldExampleLaunchInputs,
        factory=bind_bot_factory(create_random_hold_example),
    ),
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID: CatalogEntry(
        display_name="Dynamic wallet-filter copy example",
        description="Example copy strategy for selected wallets and dynamic markets.",
        label=BotDefinitionLabel.EXAMPLE,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.USER_CONFIGURED,
        launch_model=WalletFilterCopyExampleLaunchInputs,
        factory=bind_bot_factory(create_wallet_filter_copy_example),
    ),
    NODE_BASED_DEFINITION_ID: CatalogEntry(
        display_name="Node-Based Bot",
        description="Visually compose and run a paper-trading event graph.",
        label=BotDefinitionLabel.STANDARD,
        market_selection=SelectionMode.USER_CONFIGURED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=NodeBasedLaunchInputs,
        graph_capability=GraphCapability(
            catalog=GRAPH_NODE_CATALOG,
            starter_graph=STARTER_NODE_GRAPH,
            factory=NodeBasedBot,
        ),
    ),
}


def catalog_descriptors() -> tuple[BotDefinitionDescriptor, ...]:
    return tuple(
        entry.descriptor(definition_id) for definition_id, entry in CATALOG.items()
    )
