from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .prices import (
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
    is_outcome_payout,
)
from .resolution_fields import (
    RESOLUTION_RESOLVED_AT_MS_FIELD,
    RESOLUTION_SETTLED_AT_MS_FIELD,
    RESOLUTION_SOURCE_FIELD,
    RESOLUTION_WINNING_OUTCOME_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
    SETTLED_POSITION_CASH_PAYOUT_USDC_FIELD,
    SETTLED_POSITION_OWNER_FIELD,
    SETTLED_POSITION_PAYOUT_PER_TOKEN_FIELD,
    SETTLED_POSITION_REALIZED_PNL_USDC_FIELD,
    SETTLED_POSITION_SIZE_FIELD,
    SETTLED_POSITION_TOKEN_ID_FIELD,
)
from .resolution_tokens import normalize_resolution_tokens

WINNING_PAYOUT_PER_TOKEN = OUTCOME_PRICE_CEILING
LOSING_PAYOUT_PER_TOKEN = OUTCOME_PRICE_FLOOR
@dataclass(frozen=True, slots=True)
class MarketResolutionEvent:
    condition_id: str
    market_slug: str
    token_ids: tuple[str, str]
    winning_token_id: str
    winning_outcome: str
    resolved_at_ms: int
    source: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.winning_outcome, str)
            or not self.winning_outcome.strip()
        ):
            raise ValueError("market resolution outcome is invalid")
        object.__setattr__(self, "winning_outcome", self.winning_outcome.strip())
        if not self.condition_id or not self.market_slug:
            raise ValueError("market resolutions require market identity")
        token_ids, winning_token_id = normalize_resolution_tokens(
            self.token_ids,
            self.winning_token_id,
        )
        object.__setattr__(self, "token_ids", token_ids)
        object.__setattr__(self, "winning_token_id", winning_token_id)
        if self.resolved_at_ms < 0 or not self.source:
            raise ValueError("market resolution payload is incomplete")

    @property
    def source_id(self) -> str:
        return f"{self.condition_id}\0{self.winning_token_id}"

    def payout_for(self, token_id: str) -> Decimal:
        self._validate_payout_token(token_id)
        return (
            WINNING_PAYOUT_PER_TOKEN
            if token_id == self.winning_token_id
            else LOSING_PAYOUT_PER_TOKEN
        )

    def _validate_payout_token(self, token_id: str) -> None:
        if token_id not in self.token_ids:
            raise ValueError("token does not belong to the resolved market")


def realized_resolution_pnl(
    position_size: Decimal,
    average_basis: Decimal,
    payout: Decimal,
) -> Decimal:
    return (
        position_size * (payout - average_basis)
        if position_size > 0
        else abs(position_size) * (average_basis - payout)
    )


@dataclass(frozen=True, slots=True)
class SettledPosition:
    owner: str
    token_id: str
    size: Decimal
    payout_per_token: Decimal
    cash_payout_usdc: Decimal
    realized_pnl_usdc: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.owner or not self.token_id:
            raise ValueError("settled positions require owner and token identity")
        decimal_values = (
            self.size,
            self.payout_per_token,
            self.cash_payout_usdc,
        )
        if not all(value.is_finite() for value in decimal_values):
            raise ValueError("settled position values must be finite")
        if not is_outcome_payout(self.payout_per_token):
            raise ValueError("settled position payout must be between zero and one")
        if (
            self.realized_pnl_usdc is not None
            and not self.realized_pnl_usdc.is_finite()
        ):
            raise ValueError("settled position realized P&L must be finite")

    def to_payload(self) -> dict[str, Any]:
        return {
            SETTLED_POSITION_OWNER_FIELD: self.owner,
            SETTLED_POSITION_TOKEN_ID_FIELD: self.token_id,
            SETTLED_POSITION_SIZE_FIELD: str(self.size),
            SETTLED_POSITION_PAYOUT_PER_TOKEN_FIELD: str(self.payout_per_token),
            SETTLED_POSITION_CASH_PAYOUT_USDC_FIELD: str(self.cash_payout_usdc),
            SETTLED_POSITION_REALIZED_PNL_USDC_FIELD: (
                None if self.realized_pnl_usdc is None else str(self.realized_pnl_usdc)
            ),
        }


@dataclass(frozen=True, slots=True)
class MarketSettlementEvent:
    resolution: MarketResolutionEvent
    paper_positions: tuple[SettledPosition, ...]
    followed_wallet_positions: tuple[SettledPosition, ...]
    settled_at_ms: int

    @property
    def paper_cash_payout_usdc(self) -> Decimal:
        return self._cash_payout(self.paper_positions)

    @property
    def followed_wallet_cash_payout_usdc(self) -> Decimal:
        return self._cash_payout(self.followed_wallet_positions)

    @staticmethod
    def _cash_payout(positions: tuple[SettledPosition, ...]) -> Decimal:
        return sum((position.cash_payout_usdc for position in positions), Decimal("0"))
