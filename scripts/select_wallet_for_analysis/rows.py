from __future__ import annotations

from scripts.paths import GOOD_FILE
from scripts.wallet_scan_report import (
    WalletScanRecord,
    WalletScanSortField,
    load_wallet_scan_report_rows,
)

SORT_CHOICES = (
    ("n", WalletScanSortField.NET, "Net"),
    ("h", WalletScanSortField.HEDGE, "Hedge"),
    ("m", WalletScanSortField.MARKET_TRADE_PCT, "Market share"),
    ("d", WalletScanSortField.TRADE_DENSITY, "Trade density"),
    ("v", WalletScanSortField.VOLUME, "Volume"),
    ("t", WalletScanSortField.SCANNED_AT, "Scanned"),
    ("w", WalletScanSortField.WALLET, "Wallet"),
)


def load_good_wallet_rows() -> list[WalletScanRecord]:
    if not GOOD_FILE.exists():
        raise FileNotFoundError(f"missing results file: {GOOD_FILE}")
    with GOOD_FILE.open(encoding="utf-8") as source:
        rows = load_wallet_scan_report_rows(source)
    return sort_rows(rows, WalletScanSortField.NET)


def sort_rows(
    rows: list[WalletScanRecord],
    sort_key: WalletScanSortField,
    reverse: bool = True,
) -> list[WalletScanRecord]:
    return sorted(rows, key=lambda row: row.sort_value(sort_key), reverse=reverse)


def format_row(row: WalletScanRecord, width: int) -> str:
    wallet = shorten_wallet(row.wallet)
    line = (
        f"{wallet:<15} net={row.net_cash_usdc:+,.2f} "
        f"hedge={row.hedge_score:.2f} vol={row.traded_volume_usdc:,} "
        f"market={row.market_trade_pct:.2f}% "
        f"density={row.trade_density:.2f} {row.reason}"
    )
    return line[: max(0, width - 1)]


def shorten_wallet(wallet: str, prefix: int = 6, suffix: int = 4) -> str:
    if len(wallet) <= prefix + suffix + 3:
        return wallet
    return f"{wallet[:prefix]}...{wallet[-suffix:]}"
