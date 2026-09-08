"""Movement, position, and settlement contracts for followed wallets."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.events import Side
from polybot.framework.events.prices import (
    is_outcome_payout,
    is_outcome_price,
)
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    SettledPosition,
    realized_resolution_pnl,
)
from polybot.framework.position_transition import transition_signed_position
from polybot.framework.events.wallet_trades import WalletTradeEvent


@dataclass(frozen=True, slots=True)
class FollowBaseline:
    condition_id: str
    token_id: str
    market_slug: str
    size: Decimal
    basis_price: Decimal | None
    outcome: str | None = None

    def __post_init__(self) -> None:
        if not self.condition_id or not self.token_id or not self.market_slug:
            raise ValueError("followed-wallet baselines require market identity")
        if not self.size.is_finite() or self.size <= 0:
            raise ValueError("followed-wallet baseline size must be positive and finite")
        if self.basis_price is not None and not is_outcome_payout(self.basis_price):
            raise ValueError("followed-wallet baseline price must be between zero and one")


@dataclass(frozen=True, slots=True)
class FollowMovement:
    condition_id: str
    token_id: str
    side: Side
    size: Decimal
    price: Decimal
    trade_timestamp_ms: int
    source_key: str
    market_slug: str | None = None

    def __post_init__(self) -> None:
        if not self.size.is_finite() or self.size <= 0:
            raise ValueError(
                "followed-wallet movement size must be positive and finite"
            )
        if not is_outcome_price(self.price):
            raise ValueError(
                "followed-wallet movement price must be between zero and one"
            )

    @classmethod
    def from_trade(cls, trade: WalletTradeEvent) -> FollowMovement:
        return cls(
            condition_id=trade.condition_id,
            token_id=trade.token_id,
            side=trade.side,
            size=trade.size,
            price=trade.price,
            trade_timestamp_ms=trade.trade_timestamp_ms,
            source_key=trade.source_key,
            market_slug=trade.market_slug,
        )


@dataclass(frozen=True, slots=True)
class FollowPosition:
    condition_id: str
    token_id: str
    market_slug: str | None
    size: Decimal
    average_basis: Decimal | None
    realized_pnl_usdc: Decimal | None

    def apply_movement(self, movement: FollowMovement) -> FollowPosition:
        transition = transition_signed_position(
            current_size=self.size,
            current_average_basis=self.average_basis,
            side=movement.side,
            fill_size=movement.size,
            fill_price=movement.price,
        )
        realized_pnl = _add_realized_pnl(
            self.realized_pnl_usdc,
            transition.realized_pnl_delta,
        )
        return FollowPosition(
            movement.condition_id,
            movement.token_id,
            movement.market_slug or self.market_slug,
            transition.size,
            transition.average_basis,
            realized_pnl,
        )

    def resolution_pnl(self, payout: Decimal) -> Decimal | None:
        if self.average_basis is None:
            return None
        return realized_resolution_pnl(self.size, self.average_basis, payout)


def _add_realized_pnl(
    current: Decimal | None,
    delta: Decimal | None,
) -> Decimal | None:
    if current is None or delta is None:
        return None
    return current + delta


@dataclass(frozen=True, slots=True)
class SettlementCalculation:
    settled_positions: tuple[SettledPosition, ...]
    baselines: tuple[FollowBaseline, ...]
    movements: tuple[FollowMovement, ...]
    gross_realized_pnl_usdc: Decimal | None

    def to_record(
        self,
        *,
        condition_id: str,
        winning_token_id: str,
        resolved_at_ms: int,
    ) -> FollowSettlement:
        return FollowSettlement(
            condition_id=condition_id,
            winning_token_id=winning_token_id,
            resolved_at_ms=resolved_at_ms,
            positions=self.settled_positions,
            gross_realized_pnl_usdc=self.gross_realized_pnl_usdc,
            baselines=self.baselines,
            movements=self.movements,
        )


@dataclass(frozen=True, slots=True)
class FollowSettlement:
    condition_id: str
    winning_token_id: str
    resolved_at_ms: int
    positions: tuple[SettledPosition, ...]
    gross_realized_pnl_usdc: Decimal | None
    baselines: tuple[FollowBaseline, ...]
    movements: tuple[FollowMovement, ...]
