"""Typed contracts for wallet-analysis results."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TypedDict

from scripts.wallet_payload_contracts import ActivityRow, ActivityType

PNL_SIGNIFICANCE_THRESHOLD = 0.005
OPEN_POSITION_SIZE_THRESHOLD = 1.0


class WalletVerdict(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"


class WalletClassificationReason(StrEnum):
    NET_POSITIVE_DIRECTIONAL_REALIZED = "net_positive_directional_realized"
    HEDGED = "hedged"
    FEE_EATEN = "fee_eaten"
    NET_NEGATIVE_OR_FLAT = "net_negative_or_flat"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class WalletClassification:
    verdict: WalletVerdict
    reason: WalletClassificationReason
    explanation: str

    @property
    def is_good(self) -> bool:
        return self.verdict is WalletVerdict.GOOD


class WalletMetrics(TypedDict):
    activity_count: int
    trade_count: int
    first_activity_at: datetime | None
    last_activity_at: datetime | None
    activity_span_hours: float
    n_markets: int
    n_resolved: int
    n_open: int
    cash_by_activity_type: dict[ActivityType, float]
    count_by_activity_type: dict[ActivityType, int]
    net_cash: float
    volume: float
    fees: float
    gross_before_fees: float
    rewards: float
    hedge_avg: float
    wins: int
    losses: int
    open_value: float
    pm_realized: float
    pm_unrealized: float
    has_positions: bool
    net_cash_plus_open_value: float
    truncated: bool
    activity: list[ActivityRow]


@dataclass(slots=True)
class MarketMetrics:
    cash: float = 0.0
    signed_position_sizes_by_outcome: defaultdict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
