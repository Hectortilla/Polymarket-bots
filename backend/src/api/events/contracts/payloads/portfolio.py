from decimal import Decimal

from polybot.cli.observability.events import (
    PortfolioPositionSnapshot,
    PortfolioSnapshot,
)
from polybot.framework.events.prices import is_outcome_price
from polybot.framework.events.resolutions import MarketSettlementEvent
from pydantic import (
    Field,
    model_validator,
)

from api.events.contracts.payloads.base import EventPayload

PORTFOLIO_MINIMUM_POSITION_SIZE = Decimal("0")
PORTFOLIO_MINIMUM_CUMULATIVE_FEES = Decimal("0")
PORTFOLIO_EMPTY_POSITION_REQUIRES_NULL_PRICE = True
PORTFOLIO_TOKEN_IDS_MUST_BE_UNIQUE = True


class MarketSettlementPayload(EventPayload):
    settlement: MarketSettlementEvent
    portfolio: PortfolioSnapshot

    @model_validator(mode="after")
    def _validate_portfolio(self) -> "MarketSettlementPayload":
        validate_portfolio_snapshot(self.portfolio)
        return self


class PortfolioSnapshotPayload(EventPayload):
    cash_usdc: Decimal
    cumulative_fees_usdc: Decimal = Field(ge=PORTFOLIO_MINIMUM_CUMULATIVE_FEES)
    positions: tuple[PortfolioPositionSnapshot, ...]

    @model_validator(mode="after")
    def _validate_snapshot(self) -> "PortfolioSnapshotPayload":
        _validate_portfolio_values(
            self.cash_usdc,
            self.cumulative_fees_usdc,
            self.positions,
        )
        return self


def validate_portfolio_snapshot(snapshot: PortfolioSnapshot) -> None:
    _validate_portfolio_values(
        snapshot.cash_usdc,
        snapshot.cumulative_fees_usdc,
        snapshot.positions,
    )


def _validate_portfolio_values(
    cash_usdc: Decimal,
    cumulative_fees_usdc: Decimal,
    positions: tuple[PortfolioPositionSnapshot, ...],
) -> None:
    if not cash_usdc.is_finite():
        raise ValueError("portfolio cash must be finite")
    if (
        not cumulative_fees_usdc.is_finite()
        or cumulative_fees_usdc < PORTFOLIO_MINIMUM_CUMULATIVE_FEES
    ):
        raise ValueError("portfolio fees must be finite and nonnegative")
    token_ids: set[str] = set()
    for position in positions:
        duplicate_token_id = position.token_id in token_ids
        if not position.token_id or (
            PORTFOLIO_TOKEN_IDS_MUST_BE_UNIQUE and duplicate_token_id
        ):
            raise ValueError(
                "portfolio position token IDs must be non-empty and unique"
            )
        token_ids.add(position.token_id)
        if (
            not position.size.is_finite()
            or position.size < PORTFOLIO_MINIMUM_POSITION_SIZE
        ):
            raise ValueError("portfolio position size must be finite and nonnegative")
        if position.size == 0:
            if (
                PORTFOLIO_EMPTY_POSITION_REQUIRES_NULL_PRICE
                and position.average_entry_price is not None
            ):
                raise ValueError(
                    "empty portfolio positions cannot have an average price"
                )
        elif position.average_entry_price is None or not is_outcome_price(
            position.average_entry_price
        ):
            raise ValueError(
                "open portfolio positions require a valid average outcome price"
            )
