"""Persisted state contract for followed wallets."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    SettledPosition,
)

from .persistence.schema import (
    FOLLOW_ACTIVE_FIELD,
    FOLLOW_BASELINES_FIELD,
    FOLLOW_BOOTSTRAPPED_FIELD,
    FOLLOW_CHECKPOINT_FIELD,
    FOLLOW_EPOCH_FIELD,
    FOLLOW_EPOCH_HISTORY_FIELD,
    FOLLOW_MOVEMENTS_FIELD,
    FOLLOW_SETTLEMENTS_FIELD,
    FOLLOW_SOURCE_IDS_FIELD,
    FOLLOWED_AT_MS_FIELD,
)
from .position_contracts import (
    FollowBaseline,
    FollowMovement,
    FollowPosition,
    FollowSettlement,
    SettlementCalculation,
)


@dataclass(slots=True)
class WalletFollowState:
    wallet: str
    epoch: int
    active: bool
    followed_at_ms: int
    bootstrapped: bool = False
    baselines: dict[str, FollowBaseline] = field(default_factory=dict)
    movements: dict[str, FollowMovement] = field(default_factory=dict)
    source_ids: set[str] = field(default_factory=set)
    checkpoint: tuple[int, str] | None = None
    settlements: list[FollowSettlement] = field(default_factory=list)
    epoch_history: list[WalletFollowState] = field(default_factory=list)

    def has_settlement(self, condition_id: str) -> bool:
        return any(settlement.condition_id == condition_id for settlement in self.settlements)

    def gross_pnl(self, marks: dict[str, Decimal]) -> Decimal | None:
        archived_values = [settlement.gross_realized_pnl_usdc for settlement in self.settlements]
        if any(value is None for value in archived_values):
            return None
        total = sum((value for value in archived_values if value is not None), Decimal("0"))
        for position in self.replay_positions().values():
            if position.realized_pnl_usdc is None or position.average_basis is None:
                return None
            total += position.realized_pnl_usdc
            mark = marks.get(position.token_id)
            if position.size != 0 and mark is None:
                return None
            if position.size != 0:
                assert mark is not None
                total += position.size * (mark - position.average_basis)
        return total

    def to_payload(self) -> dict[str, Any]:
        return {
            FOLLOW_EPOCH_FIELD: self.epoch,
            FOLLOW_ACTIVE_FIELD: self.active,
            FOLLOWED_AT_MS_FIELD: self.followed_at_ms,
            FOLLOW_BOOTSTRAPPED_FIELD: self.bootstrapped,
            FOLLOW_BASELINES_FIELD: [
                baseline.to_payload() for baseline in self.baselines.values()
            ],
            FOLLOW_MOVEMENTS_FIELD: [
                movement.to_payload() for movement in self.movements.values()
            ],
            FOLLOW_SOURCE_IDS_FIELD: sorted(self.source_ids),
            FOLLOW_CHECKPOINT_FIELD: (
                None
                if self.checkpoint is None
                else [self.checkpoint[0], self.checkpoint[1]]
            ),
            FOLLOW_SETTLEMENTS_FIELD: [
                settlement.to_payload() for settlement in self.settlements
            ],
            FOLLOW_EPOCH_HISTORY_FIELD: [
                historical.to_epoch_payload() for historical in self.epoch_history
            ],
        }

    def to_epoch_payload(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload.pop(FOLLOW_EPOCH_HISTORY_FIELD)
        return payload

    def snapshot_epoch(self) -> WalletFollowState:
        return WalletFollowState(
            wallet=self.wallet,
            epoch=self.epoch,
            active=self.active,
            followed_at_ms=self.followed_at_ms,
            bootstrapped=self.bootstrapped,
            baselines=dict(self.baselines),
            movements=dict(self.movements),
            source_ids=set(self.source_ids),
            checkpoint=self.checkpoint,
            settlements=list(self.settlements),
        )

    def replay_positions(self) -> dict[str, FollowPosition]:
        positions: dict[str, FollowPosition] = {}
        for baseline in self.baselines.values():
            positions[baseline.token_id] = FollowPosition(
                condition_id=baseline.condition_id,
                token_id=baseline.token_id,
                market_slug=baseline.market_slug,
                size=baseline.size,
                average_basis=baseline.basis_price,
                realized_pnl_usdc=(
                    Decimal("0") if baseline.basis_price is not None else None
                ),
            )
        for movement in sorted(
            self.movements.values(),
            key=lambda movement: (movement.trade_timestamp_ms, movement.source_key),
        ):
            current = positions.get(
                movement.token_id,
                FollowPosition(
                    condition_id=movement.condition_id,
                    token_id=movement.token_id,
                    market_slug=movement.market_slug,
                    size=Decimal("0"),
                    average_basis=None,
                    realized_pnl_usdc=Decimal("0"),
                ),
            )
            positions[movement.token_id] = current.apply_movement(movement)
        return positions

    def positions(self) -> tuple[FollowPosition, ...]:
        return tuple(self.replay_positions().values())

    def calculate_settlement(
        self,
        event: MarketResolutionEvent,
    ) -> SettlementCalculation | None:
        positions = self.replay_positions()
        market_positions = tuple(
            position
            for position in positions.values()
            if position.condition_id == event.condition_id
        )
        market_movements = tuple(
            sorted(
                (
                    movement
                    for movement in self.movements.values()
                    if movement.condition_id == event.condition_id
                ),
                key=lambda movement: (movement.trade_timestamp_ms, movement.source_key),
            )
        )
        market_baselines = tuple(
            baseline
            for baseline in self.baselines.values()
            if baseline.condition_id == event.condition_id
        )
        if not market_positions and not market_movements and not market_baselines:
            return None
        settled: list[SettledPosition] = []
        gross_realized: Decimal | None = Decimal("0")
        for position in market_positions:
            if position.realized_pnl_usdc is None:
                gross_realized = None
            elif gross_realized is not None:
                gross_realized += position.realized_pnl_usdc
            if position.size == 0:
                continue
            payout = event.payout_for(position.token_id)
            realized = position.resolution_pnl(payout)
            if realized is None:
                gross_realized = None
            elif gross_realized is not None:
                gross_realized += realized
            settled.append(
                SettledPosition(
                    owner=self.wallet,
                    token_id=position.token_id,
                    size=position.size,
                    payout_per_token=payout,
                    cash_payout_usdc=position.size * payout,
                    realized_pnl_usdc=realized,
                )
            )
        return SettlementCalculation(
            settled=tuple(settled),
            baselines=market_baselines,
            movements=market_movements,
            gross_realized_pnl_usdc=gross_realized,
        )

    def apply_settlement(
        self,
        calculation: SettlementCalculation,
        settlement: FollowSettlement,
    ) -> None:
        self.settlements.append(settlement)
        for baseline in calculation.baselines:
            self.baselines.pop(baseline.token_id, None)
        for movement in calculation.movements:
            self.movements.pop(movement.source_key, None)

    def settle(
        self,
        event: MarketResolutionEvent,
    ) -> tuple[tuple[SettledPosition, ...], bool]:
        if self.has_settlement(event.condition_id):
            return (), False
        calculation = self.calculate_settlement(event)
        if calculation is None:
            return (), False
        self.apply_settlement(
            calculation,
            calculation.to_record(
                condition_id=event.condition_id,
                winning_token_id=event.winning_token_id,
                resolved_at_ms=event.resolved_at_ms,
            ),
        )
        return calculation.settled, True
