from __future__ import annotations

from scripts.wallet_scan_report import load_wallet_scan_report_rows
from scripts.paths import GOOD_FILE

SORT_CHOICES = (
    ("n", "net", "Net"), ("h", "hedge", "Hedge"),
    ("m", "market_trade_pct", "Market share"),
    ("d", "trade_density", "Trade density"), ("v", "volume", "Volume"),
    ("t", "scanned_at", "Scanned"), ("w", "wallet", "Wallet"),
)


def load_good_wallet_rows() -> list[dict[str, object]]:
    if not GOOD_FILE.exists():
        raise FileNotFoundError(f"missing results file: {GOOD_FILE}")
    with GOOD_FILE.open(encoding="utf-8") as source:
        rows = load_wallet_scan_report_rows(source)
    return sort_rows(rows, "net")


def sort_rows(
    rows: list[dict[str, object]],
    sort_key: str,
    reverse: bool = True,
) -> list[dict[str, object]]:
    default: object = "" if sort_key == "scanned_at" else 0
    return sorted(rows, key=lambda row: row.get(sort_key, default), reverse=reverse)


def format_row(row: dict[str, object], width: int) -> str:
    wallet = shorten_wallet(str(row["wallet"]))
    line = (
        f"{wallet:<15} net={float(row['net']):+,.2f} "
        f"hedge={float(row['hedge']):.2f} vol={int(row['volume']):,} "
        f"market={float(row['market_trade_pct']):.2f}% "
        f"density={float(row['trade_density']):.2f} {row['reason']}"
    )
    return line[: max(0, width - 1)]


def shorten_wallet(wallet: str, prefix: int = 6, suffix: int = 4) -> str:
    if len(wallet) <= prefix + suffix + 3:
        return wallet
    return f"{wallet[:prefix]}...{wallet[-suffix:]}"
