from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Market:
    condition_id: str
    slug: str
    question: str
    yes_token_id: str
    no_token_id: str
    minimum_tick_size: Decimal
    minimum_order_size: Decimal
    neg_risk: bool
    fee_rate: Decimal


@dataclass(frozen=True, slots=True)
class Position:
    token_id: str
    size: Decimal
    average_price: Decimal | None = None
