from polybot.cli.observability.events import (
    PortfolioSnapshot,
)
from polybot.execution.order_validation import validate_order
from polybot.framework.events import FillEvent, OrderRequest
from pydantic import (
    Field,
    NonNegativeInt,
    model_validator,
)

from api.events.contracts.payloads.base import EventPayload
from api.events.contracts.payloads.portfolio import validate_portfolio_snapshot


class BrokerOrderPayload(EventPayload):
    order: OrderRequest

    @model_validator(mode="after")
    def _validate_order(self) -> "BrokerOrderPayload":
        _validate_durable_order(self.order)
        return self


class BrokerFillPayload(EventPayload):
    order: OrderRequest
    fill: FillEvent
    portfolio: PortfolioSnapshot | None
    latency_ms: NonNegativeInt

    @model_validator(mode="after")
    def _validate_order_and_portfolio(self) -> "BrokerFillPayload":
        _validate_durable_order(self.order)
        if self.portfolio is not None:
            validate_portfolio_snapshot(self.portfolio)
        return self


class BrokerFailurePayload(EventPayload):
    order: OrderRequest
    error: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_order(self) -> "BrokerFailurePayload":
        _validate_durable_order(self.order)
        return self


def _validate_durable_order(order: OrderRequest) -> None:
    issue = validate_order(order)
    if issue is not None:
        _, detail = issue
        raise ValueError(detail)
