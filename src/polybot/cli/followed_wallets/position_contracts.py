"""Movement, position, and settlement contracts for followed wallets."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from polybot.framework.events import Side
from polybot.framework.events.prices import (
    is_outcome_payout,
    is_outcome_price,
)
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    RESOLUTION_RESOLVED_AT_MS_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
    SETTLED_POSITION_CASH_PAYOUT_USDC_FIELD,
    SETTLED_POSITION_OWNER_FIELD,
    SETTLED_POSITION_PAYOUT_PER_TOKEN_FIELD,
    SETTLED_POSITION_REALIZED_PNL_USDC_FIELD,
    SETTLED_POSITION_SIZE_FIELD,
    SETTLED_POSITION_TOKEN_ID_FIELD,
    SettledPosition,
    realized_resolution_pnl,
)
from polybot.framework.position_transition import transition_signed_position
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

    def __post_init__(self) -> None:
        if not self.condition_id or not self.token_id or not self.market_slug:
            raise ValueError("followed-wallet baselines require market identity")
        if not self.size.is_finite() or self.size <= 0:
            raise ValueError("followed-wallet baseline size must be positive and finite")
        if self.basis_price is not None and not is_outcome_payout(self.basis_price):
            raise ValueError("followed-wallet baseline price must be between zero and one")

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FollowBaseline:
        basis_price = payload[FOLLOW_BASIS_PRICE_FIELD]
        return cls(
            condition_id=payload[FOLLOW_CONDITION_ID_FIELD],
            token_id=payload[FOLLOW_TOKEN_ID_FIELD],
            market_slug=payload[FOLLOW_MARKET_SLUG_FIELD],
            size=_payload_decimal(payload[FOLLOW_SIZE_FIELD]),
            basis_price=None if basis_price is None else _payload_decimal(basis_price),
            outcome=payload.get(FOLLOW_OUTCOME_FIELD),
        )

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

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FollowMovement:
        return cls(
            condition_id=payload[FOLLOW_CONDITION_ID_FIELD],
            token_id=payload[FOLLOW_TOKEN_ID_FIELD],
            side=Side(payload[FOLLOW_SIDE_FIELD]),
            size=_payload_decimal(payload[FOLLOW_SIZE_FIELD]),
            price=_payload_decimal(payload[FOLLOW_PRICE_FIELD]),
            trade_timestamp_ms=payload[FOLLOW_TRADE_TIMESTAMP_MS_FIELD],
            source_key=payload[FOLLOW_SOURCE_KEY_FIELD],
            market_slug=payload.get(FOLLOW_MARKET_SLUG_FIELD),
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

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FollowSettlement:
        return cls(
            condition_id=payload[FOLLOW_CONDITION_ID_FIELD],
            winning_token_id=payload[RESOLUTION_WINNING_TOKEN_ID_FIELD],
            resolved_at_ms=payload[RESOLUTION_RESOLVED_AT_MS_FIELD],
            positions=tuple(
                SettledPosition(
                    owner=position[SETTLED_POSITION_OWNER_FIELD],
                    token_id=position[SETTLED_POSITION_TOKEN_ID_FIELD],
                    size=_payload_decimal(position[SETTLED_POSITION_SIZE_FIELD]),
                    payout_per_token=_payload_decimal(
                        position[SETTLED_POSITION_PAYOUT_PER_TOKEN_FIELD]
                    ),
                    cash_payout_usdc=_payload_decimal(
                        position[SETTLED_POSITION_CASH_PAYOUT_USDC_FIELD]
                    ),
                    realized_pnl_usdc=(
                        None
                        if position[SETTLED_POSITION_REALIZED_PNL_USDC_FIELD] is None
                        else _payload_decimal(
                            position[SETTLED_POSITION_REALIZED_PNL_USDC_FIELD]
                        )
                    ),
                )
                for position in payload[FOLLOW_POSITIONS_FIELD]
            ),
            gross_realized_pnl_usdc=(
                None
                if payload[FOLLOW_GROSS_REALIZED_PNL_FIELD] is None
                else _payload_decimal(payload[FOLLOW_GROSS_REALIZED_PNL_FIELD])
            ),
            baselines=tuple(
                FollowBaseline.from_payload(baseline)
                for baseline in payload[FOLLOW_BASELINES_FIELD]
            ),
            movements=tuple(
                FollowMovement.from_payload(movement)
                for movement in payload[FOLLOW_MOVEMENTS_FIELD]
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            FOLLOW_CONDITION_ID_FIELD: self.condition_id,
            RESOLUTION_WINNING_TOKEN_ID_FIELD: self.winning_token_id,
            RESOLUTION_RESOLVED_AT_MS_FIELD: self.resolved_at_ms,
            FOLLOW_POSITIONS_FIELD: [
                position.to_payload() for position in self.positions
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


def _payload_decimal(value: object) -> Decimal:
    """Use the same text conversion as persisted-payload validation."""

    return Decimal(str(value))
