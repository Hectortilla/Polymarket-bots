from __future__ import annotations

from datetime import datetime, timezone

from polybot.framework.wallets import normalize_wallet_address
from scripts.wallet_analysis.contracts import (
    HEDGE_AVERAGE_METRIC,
    NET_CASH_METRIC,
    VOLUME_METRIC,
    WalletClassificationReason,
    WalletMetrics,
    WalletVerdict,
)
from scripts.wallet_payload_contracts import PROXY_WALLET_FIELD, PositionRow
from scripts.wallet_scan_report import format_wallet_scan_record


def unique_holders(positions: list[PositionRow]) -> list[tuple[str, PositionRow]]:
    holders = []
    seen = set()
    for position in positions:
        wallet = normalize_wallet_address(str(position.get(PROXY_WALLET_FIELD) or ""))
        if wallet and wallet not in seen:
            seen.add(wallet)
            holders.append((wallet, position))
    return holders


def result_note(
    verdict: WalletVerdict,
    metrics: WalletMetrics,
    market_share: float,
    trades_per_day: float,
    reason: WalletClassificationReason,
) -> str:
    return format_wallet_scan_record(
        label=verdict,
        net=metrics[NET_CASH_METRIC], hedge=metrics[HEDGE_AVERAGE_METRIC],
        volume=metrics[VOLUME_METRIC], market_trade_pct=market_share,
        trade_density=trades_per_day, reason=reason,
        scanned_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
