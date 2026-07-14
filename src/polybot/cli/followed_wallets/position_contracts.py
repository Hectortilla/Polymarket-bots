"""Movement, position, and settlement contracts for followed wallets."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from polybot.framework.events import Side
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    RESOLUTION_RESOLVED_AT_MS_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
    SettledPosition,
    realized_resolution_pnl,
)
from polybot.framework.events.wallet_trades import WalletTradeEvent

from .persistence.schema import (
    FOLLOW_BASIS_PRICE_FIELD,
    FOLLOW_CONDITION_ID_FIELD,
    FOLLOW_MARKET_SLUG_FIELD,
    FOLLOW_MOVEMENTS_FIELD,
    FOLLOW_OUTCOME_FIELD,
    FOLLOW_POSITIONS_FIELD,
    FOLLOW_PRICE_FIELD,
    FOLLOW_SIDE_FIELD,
    FOLLOW_SIZE_FIELD,
    FOLLOW_SOURCE_KEY_FIELD,
    FOLLOW_TOKEN_ID_FIELD,
    FOLLOW_TRADE_TIMESTAMP_MS_FIELD,
    FOLLOW_BASELINES_FIELD,
    FOLLOW_GROSS_REALIZED_PNL_FIELD,
)


@dataclass(frozen=True, slots=True)
class FollowBaseline:
    condition_id: str
    token_id: str
    market_slug: str
    size: Decimal
    basis_price: Decimal | None
    outcome: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            FOLLOW_CONDITION_ID_FIELD: self.condition_id,
            FOLLOW_TOKEN_ID_FIELD: self.token_id,
            FOLLOW_MARKET_SLUG_FIELD: self.market_slug,
            FOLLOW_SIZE_FIELD: str(self.size),
            FOLLOW_BASIS_PRICE_FIELD: (
                None if self.basis_price is None else str(self.basis_price)
            ),
            FOLLOW_OUTCOME_FIELD: self.outcome,
        }


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
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError(
                "followed-wallet movement price must be positive and finite"
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

    def to_payload(self) -> dict[str, Any]:
        return {
            FOLLOW_CONDITION_ID_FIELD: self.condition_id,
            FOLLOW_TOKEN_ID_FIELD: self.token_id,
            FOLLOW_SIDE_FIELD: self.side.value,
            FOLLOW_SIZE_FIELD: str(self.size),
            FOLLOW_PRICE_FIELD: str(self.price),
            FOLLOW_TRADE_TIMESTAMP_MS_FIELD: self.trade_timestamp_ms,
            FOLLOW_SOURCE_KEY_FIELD: self.source_key,
            FOLLOW_MARKET_SLUG_FIELD: self.market_slug,
        }


@dataclass(frozen=True, slots=True)
class FollowPosition:
    condition_id: str
    token_id: str
    market_slug: str | None
    size: Decimal
    average_basis: Decimal | None
    realized_pnl_usdc: Decimal | None

    def apply_movement(self, movement: FollowMovement) -> FollowPosition:
        signed_size = movement.size if movement.side is Side.BUY else -movement.size
        if self.size == 0 or self.size * signed_size > 0:
            new_size = self.size + signed_size
            return FollowPosition(
                movement.condition_id,
                movement.token_id,
                movement.market_slug or self.market_slug,
                new_size,
                self._average_basis_after_increase(movement, new_size, signed_size),
                self.realized_pnl_usdc,
            )
        closed_size = min(abs(self.size), abs(signed_size))
        realized_pnl = self.realized_pnl_usdc
        if realized_pnl is not None and self.average_basis is not None:
            unit_pnl = (
                movement.price - self.average_basis
                if self.size > 0
                else self.average_basis - movement.price
            )
            realized_pnl += closed_size * unit_pnl
        else:
            realized_pnl = None
        new_size = self.size + signed_size
        average_basis = self.average_basis
        if new_size == 0:
            average_basis = None
        elif self.size * new_size < 0:
            average_basis = movement.price
        return FollowPosition(
            movement.condition_id,
            movement.token_id,
            movement.market_slug or self.market_slug,
            new_size,
            average_basis,
            realized_pnl,
        )

    def _average_basis_after_increase(
        self,
        movement: FollowMovement,
        new_size: Decimal,
        signed_size: Decimal,
    ) -> Decimal | None:
        if self.size == 0:
            return movement.price
        if self.average_basis is None:
            return None
        return (
            abs(self.size) * self.average_basis + abs(signed_size) * movement.price
        ) / abs(new_size)

    def resolution_pnl(self, payout: Decimal) -> Decimal | None:
        if self.average_basis is None:
            return None
        return realized_resolution_pnl(self.size, self.average_basis, payout)


@dataclass(frozen=True, slots=True)
class SettlementCalculation:
    settled: tuple[SettledPosition, ...]
    baselines: tuple[FollowBaseline, ...]
    movements: tuple[FollowMovement, ...]
    gross_realized_pnl_usdc: Decimal | None

    def to_payload(
        self,
        *,
        condition_id: str,
        winning_token_id: str,
        resolved_at_ms: int,
    ) -> dict[str, Any]:
        return {
            FOLLOW_CONDITION_ID_FIELD: condition_id,
            RESOLUTION_WINNING_TOKEN_ID_FIELD: winning_token_id,
            RESOLUTION_RESOLVED_AT_MS_FIELD: resolved_at_ms,
            FOLLOW_POSITIONS_FIELD: [
                position.to_payload() for position in self.settled
            ],
            FOLLOW_GROSS_REALIZED_PNL_FIELD: (
                None
                if self.gross_realized_pnl_usdc is None
                else str(self.gross_realized_pnl_usdc)
            ),
            FOLLOW_BASELINES_FIELD: [
                baseline.to_payload() for baseline in self.baselines
            ],
            FOLLOW_MOVEMENTS_FIELD: [
                movement.to_payload() for movement in self.movements
            ],
        }
