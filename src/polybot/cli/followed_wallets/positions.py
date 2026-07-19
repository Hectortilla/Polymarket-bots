"""Pure marked P&L calculations for followed-wallet positions."""

from __future__ import annotations

from collections.abc import Mapping

from polybot.framework.events.resolutions import MarketResolutionEvent, SettledPosition

from .contracts import WalletFollowState
from .position_contracts import FollowPosition


def tracked_market_positions(
    states: Mapping[str, WalletFollowState],
) -> tuple[tuple[str, FollowPosition], ...]:
    positions: list[tuple[str, FollowPosition]] = []
    for state in states.values():
        positions.extend((state.wallet, position) for position in state.positions())
        for historical in state.epoch_history:
            positions.extend(
                (state.wallet, position) for position in historical.positions()
            )
    return tuple(positions)


def settle_states(
    states: Mapping[str, WalletFollowState],
    event: MarketResolutionEvent,
) -> tuple[tuple[SettledPosition, ...], bool]:
    settled: list[SettledPosition] = []
    changed = False
    for state in states.values():
        current_settled, current_changed = state.settle(event)
        settled.extend(current_settled)
        changed = changed or current_changed
        for historical in state.epoch_history:
            historical_settled, historical_changed = historical.settle(event)
            if historical_changed:
                changed = True
            settled.extend(historical_settled)
    return tuple(settled), changed
