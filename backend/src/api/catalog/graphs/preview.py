"""Preview ingress: framework-validated events and isolated portfolio samples."""

from dataclasses import replace
from decimal import Decimal
from inspect import signature
from typing import Any, Self, get_type_hints

from polybot.framework.base import BaseBot
from polybot.framework.config.constants import DEFAULT_EVENT_MAX_AGE_MS
from polybot.framework.events import OrderRequest
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.portfolio import PortfolioPosition, PortfolioSnapshot
from polybot.framework.wallets import validate_wallet_address
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    TypeAdapter,
    model_validator,
)

from api.catalog.graphs.contracts import NodeGraph
from api.catalog.graphs.preview_samples import DEFAULT_PREVIEW_CASH
from api.catalog.graphs.results import GraphNodeEvaluationRead
from api.catalog.graphs.types import GraphHookName
from api.catalog.graphs.values import GraphNodeType


class PreviewPortfolio(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    available_cash: Decimal = Field(default=DEFAULT_PREVIEW_CASH, allow_inf_nan=False)
    positions: tuple[PortfolioPosition, ...] = ()

    @model_validator(mode="after")
    def _validate_positions(self) -> Self:
        tokens: set[str] = set()
        for position in self.positions:
            if not position.token_id or position.token_id in tokens:
                raise ValueError("Portfolio tokens must be nonempty and unique")
            tokens.add(position.token_id)
            if (
                not position.size.is_finite()
                or position.average_entry_price is not None
                and not position.average_entry_price.is_finite()
            ):
                raise ValueError("Portfolio numbers must be finite")
            if (position.size == 0) != (position.average_entry_price is None):
                raise ValueError("Only nonzero positions have an average entry price")
        return self

    def snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(self.available_cash, self.positions)


class GraphPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graph: NodeGraph
    hook_name: GraphHookName
    payload: dict[str, Any] | None = None
    portfolio: PreviewPortfolio | None = Field(default_factory=PreviewPortfolio)
    now_ms: int = Field(ge=0, strict=True)
    _event: object | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _validate_event(self) -> Self:
        if not any(
            node.type == GraphNodeType.TRIGGER and node.data.hook_name == self.hook_name
            for node in self.graph.nodes
        ):
            raise ValueError("Select a trigger present in this graph")
        method = getattr(BaseBot, self.hook_name)
        parameters = tuple(signature(method).parameters.values())
        if len(parameters) == 2:
            if self.payload is not None:
                raise ValueError("This lifecycle trigger has no payload")
        else:
            annotation = get_type_hints(method)[parameters[-1].name]
            self._event = TypeAdapter(annotation).validate_python(self.payload)
            self._validate_event_semantics()
        return self

    def _validate_event_semantics(self) -> None:
        event = self._event
        if isinstance(event, BookSnapshot):
            event = replace(event, token_id=event.token_id.strip())
            self._event = event
            if not event.token_id:
                raise ValueError("Preview book token ID must be nonempty")
            issue = event.validation_issue(self.now_ms, DEFAULT_EVENT_MAX_AGE_MS)
            if issue is not None:
                raise ValueError(issue.value)
        elif isinstance(event, WalletTradeEvent):
            event = replace(
                event,
                wallet=validate_wallet_address(event.wallet),
                token_id=event.token_id.strip(),
            )
            self._event = event
            issue = event.validation_issue(self.now_ms, DEFAULT_EVENT_MAX_AGE_MS)
            if issue is not None:
                raise ValueError(issue.value)

    @property
    def event(self) -> object | None:
        return self._event


class GraphPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: tuple[GraphNodeEvaluationRead, ...]
    intended_orders: tuple[OrderRequest, ...]
