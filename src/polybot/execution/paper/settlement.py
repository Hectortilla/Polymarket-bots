"""Pure paper-portfolio resolution calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from polybot.framework.events.resolutions import SettledPosition


@dataclass(frozen=True, slots=True)
class PaperSettlementCalculation:
    settled_positions: tuple[SettledPosition, ...]
    cash_delta: Decimal
    settled_token_ids: frozenset[str]
