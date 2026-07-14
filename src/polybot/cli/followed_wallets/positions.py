"""Pure marked P&L calculations for followed-wallet positions."""

from __future__ import annotations

from collections.abc import Mapping

from polybot.framework.events.resolutions import MarketResolutionEvent, SettledPosition

from .contracts import WalletFollowState
from .position_contracts import FollowPosition
from .persistence.serialization import state_from_payload


def tracked_market_positions(
    states: Mapping[str, WalletFollowState],
) -> tuple[tuple[str, FollowPosition], ...]:
    positions: list[tuple[str, FollowPosition]] = []
    for state in states.values():
        positions.extend((state.wallet, position) for position in state.positions())
        for payload in state.epoch_history:
            historical = state_from_payload(state.wallet, payload)
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
        for index, payload in enumerate(state.epoch_history):
            historical = state_from_payload(state.wallet, payload)
            historical_settled, historical_changed = historical.settle(event)
            if historical_changed:
                state.epoch_history[index] = historical.to_epoch_payload()
                changed = True
            settled.extend(historical_settled)
    return tuple(settled), changed
