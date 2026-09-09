"""Public paper-run contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from polybot.framework.config.constants import (
    MAX_DATA_TRADES_PER_RATE_LIMIT_WINDOW,
    MIN_DATA_TRADES_PER_RATE_LIMIT_WINDOW,
)
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.framework.streams import StreamPlan, StreamRule
from polybot.performance.contracts.valuation_status import ValuationStatus
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
)

from api.bots.revisions import GraphRevisionNumber
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.values import DefinitionId
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.limits.policy import PAPER_BETA
from api.runs import status as run_status

type RunName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
type DataTradesBudget = Annotated[
    StrictInt,
    Field(
        ge=MIN_DATA_TRADES_PER_RATE_LIMIT_WINDOW,
        le=MAX_DATA_TRADES_PER_RATE_LIMIT_WINDOW,
    ),
]
type PositiveDecimal = Annotated[Decimal, Field(gt=0)]
type NonnegativeDecimal = Annotated[Decimal, Field(ge=0)]
type NonnegativeMilliseconds = Annotated[StrictInt, Field(ge=0)]


class PaperRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RunName
    stream_rules: tuple[StreamRule, ...]
    data_trades_budget_per_10s: DataTradesBudget
    max_order_size: PositiveDecimal
    max_slippage_pct: NonnegativeDecimal
    paper_latency_ms: NonnegativeMilliseconds
    paper_latency_jitter_ms: NonnegativeMilliseconds
    event_max_age_ms: NonnegativeMilliseconds
    paper_portfolio_usdc: PositiveDecimal

    @field_validator("stream_rules", mode="before")
    @classmethod
    def _validate_persisted_stream_rules(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        return tuple(
            rule if isinstance(rule, StreamRule) else StreamRule.from_dict(rule)
            for rule in value
        )

    def require_subscription_allowance(self) -> None:
        subscriptions = StreamPlan(self.stream_rules)
        if (
            len(subscriptions.current_market_slugs) > PAPER_BETA.tracked_markets_per_run
            or len(subscriptions.current_wallet_addresses)
            > PAPER_BETA.followed_wallets_per_run
        ):
            raise ResourceLimitError(
                ResourceLimitCode.INVALID_CONFIGURATION,
                f"Run configuration exceeds the beta allowance of {PAPER_BETA.tracked_markets_per_run} markets or {PAPER_BETA.followed_wallets_per_run} followed wallets. Edit the bot before launching.",
            )

    def to_bot_config(self) -> BotConfig:
        # The web boundary is paper-only: persisted input cannot select live
        # mode or smuggle credentials into the existing runtime contract.
        return BotConfig(
            name=self.name,
            mode=BotMode.PAPER,
            stream_rules=self.stream_rules,
            data_trades_budget_per_10s=self.data_trades_budget_per_10s,
            max_order_size=self.max_order_size,
            max_slippage_pct=self.max_slippage_pct,
            paper_latency_ms=self.paper_latency_ms,
            paper_latency_jitter_ms=self.paper_latency_jitter_ms,
            event_max_age_ms=self.event_max_age_ms,
            paper_portfolio_usdc=self.paper_portfolio_usdc,
            live_enabled=False,
            private_key=None,
            api_key=None,
            api_secret=None,
            api_passphrase=None,
            funder_address=None,
        )


class RunRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    bot_id: UUID
    definition_id: DefinitionId
    config: PaperRunConfig
    bot_graph_revision_id: UUID | None = None
    graph_revision: GraphRevisionNumber | None = None
    graph: NodeGraph | None = None
    status: run_status.RunStatus
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    heartbeat_at: datetime | None = None
    failure_detail: str | None = None
    latest_runtime_failure: str | None = None
    latest_equity: Decimal | None = None
    equity_status: ValuationStatus | None = None

    def with_event_summary(
        self,
        *,
        latest_equity: Decimal | None = None,
        equity_status: ValuationStatus | None = None,
        latest_runtime_failure: str | None = None,
    ) -> RunRead:
        if equity_status is None and latest_runtime_failure is None:
            return self
        updates: dict[str, object] = {}
        if equity_status is not None:
            updates.update(latest_equity=latest_equity, equity_status=equity_status)
        if latest_runtime_failure is not None:
            updates["latest_runtime_failure"] = latest_runtime_failure
        return self.model_copy(update=updates)


class ClaimedRunRead(RunRead):
    started_at: datetime
    execution_token: UUID
