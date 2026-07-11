from __future__ import annotations

from datetime import datetime, timezone

from polybot.framework.wallets import normalize_wallet_address
from scripts.wallet_analysis import WalletMetrics, WalletVerdict
from scripts.wallet_payloads import PROXY_WALLET_FIELD, PositionRow
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
    density: float,
    reason: str,
) -> str:
    return format_wallet_scan_record(
        label=verdict,
        net=metrics["net_cash"], hedge=metrics["hedge_avg"],
        volume=metrics["volume"], market_trade_pct=market_share,
        trade_density=density, reason=reason,
        scanned_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
