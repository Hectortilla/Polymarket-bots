"""Wallet-follow lifecycle, persistence orchestration, and accounting access."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from time import time
from typing import Any

from polybot.async_io import run_blocking
from polybot.cli.persistence import AtomicJsonFile
from polybot.framework.events.resolutions import MarketResolutionEvent, SettledPosition
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.wallets import normalize_wallet_address
from polybot.polymarket.types import Position

from .contracts import WalletFollowState
from .position_contracts import FollowBaseline, FollowMovement, FollowPosition
from .persistence.serialization import load_states, root_payload
from .positions import (
    settle_states,
    tracked_market_positions as collect_tracked_market_positions,
)


class FollowedWalletTracker:
    def __init__(self, path: Path, *, now_ms: Callable[[], int] | None = None) -> None:
        self._file = AtomicJsonFile(path)
        self._now_ms = now_ms or (lambda: int(time() * 1000))
        self._wallets = load_states(self._file.read())

    @classmethod
    async def create(
        cls,
        path: Path,
        *,
        now_ms: Callable[[], int] | None = None,
    ) -> FollowedWalletTracker:
        """Load persisted follow state without blocking the event loop."""

        tracker = cls.__new__(cls)
        tracker._file = AtomicJsonFile(path)
        tracker._now_ms = now_ms or (lambda: int(time() * 1000))
        payload = await run_blocking(tracker._file.read)
        tracker._wallets = load_states(payload)
        return tracker

    @property
    def active_wallets(self) -> tuple[str, ...]:
        return tuple(
            sorted(wallet for wallet, state in self._wallets.items() if state.active)
        )

    def state(self, wallet: str) -> WalletFollowState | None:
        return self._wallets.get(normalize_wallet_address(wallet))

    def synchronize(self, wallets: tuple[str, ...]) -> tuple[str, ...]:
        selected = {normalize_wallet_address(wallet) for wallet in wallets}
        changed = False
        for state in self._wallets.values():
            if state.active and state.wallet not in selected:
                state.active = False
                changed = True
        new_wallets: list[str] = []
        for wallet in sorted(selected):
            state = self._wallets.get(wallet)
            if state is None:
                self._wallets[wallet] = WalletFollowState(
                    wallet=wallet,
                    epoch=1,
                    active=True,
                    followed_at_ms=0,
                )
                new_wallets.append(wallet)
                changed = True
            elif not state.active:
                state.epoch_history.append(state.to_epoch_payload())
                state.epoch += 1
                state.active = True
                state.followed_at_ms = 0
                state.bootstrapped = False
                state.baselines.clear()
                state.movements.clear()
                state.source_ids.clear()
                state.checkpoint = None
                state.settlements.clear()
                new_wallets.append(wallet)
                changed = True
            elif not state.bootstrapped:
                new_wallets.append(wallet)
        if changed:
            self.persist()
        return tuple(new_wallets)

    def bootstrap(
        self,
        wallet: str,
        positions: tuple[tuple[Position, Decimal | None], ...],
    ) -> None:
        state = self._required_active(wallet)
        for position, mark in positions:
            state.baselines[position.token_id] = FollowBaseline(
                condition_id=position.condition_id,
                token_id=position.token_id,
                market_slug=position.market_slug,
                size=position.size,
                basis_price=mark,
                outcome=position.outcome,
            )
        state.followed_at_ms = self._now_ms()
        state.bootstrapped = True
        self.persist()

    def mark_baseline(self, token_id: str, price: Decimal) -> bool:
        changed = False
        for state in self._wallets.values():
            baseline = state.baselines.get(token_id)
            if state.active and baseline is not None and baseline.basis_price is None:
                state.baselines[token_id] = FollowBaseline(
                    condition_id=baseline.condition_id,
                    token_id=baseline.token_id,
                    market_slug=baseline.market_slug,
                    size=baseline.size,
                    basis_price=price,
                    outcome=baseline.outcome,
                )
                changed = True
        if changed:
            self.persist()
        return changed

    def record_trade(self, trade: WalletTradeEvent) -> bool:
        state = self.state(trade.wallet)
        if (
            state is None
            or not state.active
            or not state.bootstrapped
            or trade.source_key in state.source_ids
        ):
            return False
        movement = FollowMovement.from_trade(trade)
        state.movements[movement.source_key] = movement
        state.source_ids.add(movement.source_key)
        checkpoint = (movement.trade_timestamp_ms, movement.source_key)
        if state.checkpoint is None or checkpoint > state.checkpoint:
            state.checkpoint = checkpoint
        self.persist()
        return True

    def positions(self, wallet: str) -> tuple[FollowPosition, ...]:
        return self._required_active(wallet).positions()

    def gross_pnl(self, wallet: str, marks: dict[str, Decimal]) -> Decimal | None:
        return self._required_active(wallet).gross_pnl(marks)

    def open_market_slugs(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                position.market_slug
                for _, position in self.tracked_market_positions()
                if position.size != 0 and position.market_slug
            )
        )

    def tracked_market_positions(self) -> tuple[tuple[str, FollowPosition], ...]:
        return collect_tracked_market_positions(self._wallets)

    def settle(self, event: MarketResolutionEvent) -> tuple[SettledPosition, ...]:
        settled, changed = settle_states(self._wallets, event)
        if changed:
            self.persist()
        return settled

    def persist(self) -> None:
        self._file.write(root_payload(self._wallets))

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(root_payload(self._wallets))

    def restore(self, snapshot: dict[str, Any]) -> None:
        self._wallets = load_states(deepcopy(snapshot))
        self.persist()

    def _required_active(self, wallet: str) -> WalletFollowState:
        state = self.state(wallet)
        if state is None or not state.active:
            raise ValueError("wallet does not have an active follow epoch")
        return state
