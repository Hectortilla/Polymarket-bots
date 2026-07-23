"""Internal position contract normalized from official SDK responses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Position:
    token_id: str
    size: Decimal
    average_price: Decimal | None = None
    condition_id: str | None = None
    market_slug: str | None = None
    outcome: str | None = None
    current_price: Decimal | None = None
