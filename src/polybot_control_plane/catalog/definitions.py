"""Initial trusted bot definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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
from polybot.framework.factories import BoundBotFactory, bind_bot_factory
from polybot_control_plane.catalog.contracts import (
    BotDefinitionDescriptor,
    BotDefinitionLabel,
    DefinitionId,
    DefinitionVersion,
    SelectionMode,
)
from polybot_control_plane.catalog.inputs import (
    ContrarianLaunchInputs,
    MarketWatcherLaunchInputs,
    MomentumExampleLaunchInputs,
    PaperLaunchInputs,
    RandomHoldExampleLaunchInputs,
    WalletFilterCopyExampleLaunchInputs,
    WinnerLaunchInputs,
)

if TYPE_CHECKING:
    from polybot.framework.factories import BotFactory
    from polybot.framework.config.models import BotConfig
    from polybot_control_plane.runs.contracts import PaperRunConfig


INITIAL_DEFINITION_VERSION = 1
WINNER_DEFINITION_ID = "btc-five-minute-winner"
MOMENTUM_EXAMPLE_DEFINITION_ID = "btc-five-minute-momentum-example"
CONTRARIAN_DEFINITION_ID = "btc-five-minute-contrarian"
MARKET_WATCHER_DEFINITION_ID = "btc-five-minute-market-watcher"
RANDOM_HOLD_EXAMPLE_DEFINITION_ID = "dynamic-random-hold-example"
WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID = (
    "dynamic-wallet-filter-copy-example"
)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    version: DefinitionVersion
    display_name: str
    description: str
    label: BotDefinitionLabel
    market_selection: SelectionMode
    wallet_selection: SelectionMode
    launch_model: type[PaperLaunchInputs]
    factory: BotFactory
    _bound_factory: BoundBotFactory = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_bound_factory", bind_bot_factory(self.factory))

    def descriptor(self, definition_id: DefinitionId) -> BotDefinitionDescriptor:
        return BotDefinitionDescriptor(
            definition_id=definition_id,
            version=self.version,
            display_name=self.display_name,
            description=self.description,
            label=self.label,
            market_selection=self.market_selection,
            wallet_selection=self.wallet_selection,
            input_schema=self.launch_model.model_json_schema(),
        )

    def parse_config(self, inputs: object) -> PaperRunConfig:
        return self.launch_model.model_validate(inputs).to_run_config()

    def matches_version(self, version: DefinitionVersion) -> bool:
        return self.version == version

    def create_bot(self, bot_config: BotConfig):
        return self._bound_factory(bot_config)


CATALOG: dict[str, CatalogEntry] = {
    WINNER_DEFINITION_ID: CatalogEntry(
        version=INITIAL_DEFINITION_VERSION,
        display_name="BTC five-minute winner",
        description="Trades a strong late leader in consecutive BTC markets.",
        label=BotDefinitionLabel.STANDARD,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=WinnerLaunchInputs,
        factory=create_winner,
    ),
    MOMENTUM_EXAMPLE_DEFINITION_ID: CatalogEntry(
        version=INITIAL_DEFINITION_VERSION,
        display_name="BTC five-minute momentum example",
        description="Example strategy driven by paired outcome-book momentum.",
        label=BotDefinitionLabel.EXAMPLE,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=MomentumExampleLaunchInputs,
        factory=create_momentum_example,
    ),
    CONTRARIAN_DEFINITION_ID: CatalogEntry(
        version=INITIAL_DEFINITION_VERSION,
        display_name="BTC five-minute contrarian",
        description="Trades a selective late reversal in consecutive BTC markets.",
        label=BotDefinitionLabel.STANDARD,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=ContrarianLaunchInputs,
        factory=create_contrarian,
    ),
    MARKET_WATCHER_DEFINITION_ID: CatalogEntry(
        version=INITIAL_DEFINITION_VERSION,
        display_name="BTC five-minute market watcher",
        description="Observes consecutive BTC markets without trading.",
        label=BotDefinitionLabel.NON_TRADING,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=MarketWatcherLaunchInputs,
        factory=create_market_watcher,
    ),
    RANDOM_HOLD_EXAMPLE_DEFINITION_ID: CatalogEntry(
        version=INITIAL_DEFINITION_VERSION,
        display_name="Dynamic random-hold example",
        description="Example random-hold strategy for consecutive BTC markets.",
        label=BotDefinitionLabel.EXAMPLE,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.ABSENT,
        launch_model=RandomHoldExampleLaunchInputs,
        factory=create_random_hold_example,
    ),
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID: CatalogEntry(
        version=INITIAL_DEFINITION_VERSION,
        display_name="Dynamic wallet-filter copy example",
        description="Example copy strategy for selected wallets and dynamic markets.",
        label=BotDefinitionLabel.EXAMPLE,
        market_selection=SelectionMode.BOT_MANAGED,
        wallet_selection=SelectionMode.USER_CONFIGURED,
        launch_model=WalletFilterCopyExampleLaunchInputs,
        factory=create_wallet_filter_copy_example,
    ),
}


def catalog_descriptors() -> tuple[BotDefinitionDescriptor, ...]:
    return tuple(
        entry.descriptor(definition_id)
        for definition_id, entry in CATALOG.items()
    )
