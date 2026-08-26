"""Public paper-run contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
)

from polybot.framework.config.constants import MAX_DATA_TRADES_PER_RATE_LIMIT_WINDOW
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.framework.streams import StreamRule
from polybot.performance.contracts.valuation_status import ValuationStatus
from polybot_control_plane.catalog.contracts import DefinitionId
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.runs.status import RunStatus


type RunName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
type DataTradesBudget = Annotated[
    StrictInt,
    Field(ge=1, le=MAX_DATA_TRADES_PER_RATE_LIMIT_WINDOW),
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
    graph: NodeGraph | None = Field(
        default=None,
        # Keep non-node run snapshots unchanged while retaining node graphs exactly.
        exclude_if=lambda graph: graph is None,
    )

    @field_validator("stream_rules", mode="before")
    @classmethod
    def _validate_persisted_stream_rules(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        return tuple(
            rule if isinstance(rule, StreamRule) else StreamRule.from_dict(rule)
            for rule in value
        )

    def to_bot_config(self) -> BotConfig:
        # The web boundary is paper-only: persisted input cannot select live
        # mode or smuggle credentials into the existing runtime contract. MVP
        # graphs are storage-only and cannot influence runtime decisions or orders.
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
    definition_id: DefinitionId
    config: PaperRunConfig
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    heartbeat_at: datetime | None = None
    failure_detail: str | None = None
    latest_equity: Decimal | None = None
    equity_status: ValuationStatus | None = None
