from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polybot.polymarket.types import Market


YES_OUTCOME = "Yes"
NO_OUTCOME = "No"
WINNING_PAYOUT_PER_TOKEN = Decimal("1")
LOSING_PAYOUT_PER_TOKEN = Decimal("0")
RESOLUTION_WINNING_TOKEN_ID_FIELD = "winning_token_id"
RESOLUTION_WINNING_OUTCOME_FIELD = "winning_outcome"
RESOLUTION_RESOLVED_AT_MS_FIELD = "resolved_at_ms"
RESOLUTION_SETTLED_AT_MS_FIELD = "settled_at_ms"
RESOLUTION_SOURCE_FIELD = "source"
GAMMA_RECONCILIATION_SOURCE = "gamma_reconciliation"


SETTLED_POSITION_OWNER_FIELD = "owner"
SETTLED_POSITION_TOKEN_ID_FIELD = "token_id"
SETTLED_POSITION_SIZE_FIELD = "size"
SETTLED_POSITION_PAYOUT_PER_TOKEN_FIELD = "payout_per_token"
SETTLED_POSITION_CASH_PAYOUT_USDC_FIELD = "cash_payout_usdc"
SETTLED_POSITION_REALIZED_PNL_USDC_FIELD = "realized_pnl_usdc"


@dataclass(frozen=True, slots=True)
class MarketResolutionEvent:
    condition_id: str
    market_slug: str
    token_ids: tuple[str, str]
    winning_token_id: str
    winning_outcome: str
    resolved_at_ms: int
    source: str

    @classmethod
    def from_market(
        cls,
        market: Market,
        *,
        resolved_at_ms: int,
        source: str,
    ) -> MarketResolutionEvent | None:
        if (
            not market.resolved
            or market.winning_token_id is None
            or market.winning_outcome is None
        ):
            return None
        return cls(
            condition_id=market.condition_id,
            market_slug=market.slug,
            token_ids=market.token_ids,
            winning_token_id=market.winning_token_id,
            winning_outcome=market.winning_outcome,
            resolved_at_ms=resolved_at_ms,
            source=source,
        )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.winning_outcome, str)
            or not self.winning_outcome.strip()
        ):
            raise ValueError("market resolution outcome is invalid")
        object.__setattr__(self, "winning_outcome", self.winning_outcome.strip())
        if not self.condition_id or not self.market_slug:
            raise ValueError("market resolutions require market identity")
        if len(set(self.token_ids)) != 2 or any(
            not token_id for token_id in self.token_ids
        ):
            raise ValueError("market resolutions require two distinct token IDs")
        if self.winning_token_id not in self.token_ids:
            raise ValueError("winning token must belong to the resolved market")
        if self.resolved_at_ms < 0 or not self.source:
            raise ValueError("market resolution payload is incomplete")

    @property
    def source_id(self) -> str:
        return f"{self.condition_id}\0{self.winning_token_id}"

    def payout_for(self, token_id: str) -> Decimal:
        self._validate_payout_token(token_id)
        return _payout_for_winner(token_id == self.winning_token_id)

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


def _payout_for_winner(is_winner: bool) -> Decimal:
    return WINNING_PAYOUT_PER_TOKEN if is_winner else LOSING_PAYOUT_PER_TOKEN
