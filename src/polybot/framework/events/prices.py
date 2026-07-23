"""Shared bounds for normalized binary-outcome prices and payouts."""

from __future__ import annotations

from decimal import Decimal


OUTCOME_PRICE_FLOOR = Decimal("0")
OUTCOME_PRICE_CEILING = Decimal("1")
