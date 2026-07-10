from __future__ import annotations

import shlex
import sys
from collections.abc import Iterable
from typing import TypedDict

from scripts.wallet_analysis import WalletVerdict

WALLET_SCAN_FIELD_COUNT = 9


class WalletScanRecord(TypedDict):
    wallet: str
    label: WalletVerdict
    net: float
    hedge: float
    volume: int
    market_trade_pct: float
    trade_density: float
    reason: str
    scanned_at: str


def parse_wallet_scan_report_line(line: str) -> WalletScanRecord | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    fields = shlex.split(line)
    if len(fields) != WALLET_SCAN_FIELD_COUNT:
        raise ValueError(
            f"expected {WALLET_SCAN_FIELD_COUNT} fields, got {len(fields)}"
        )
    wallet, label, net, hedge, volume, market_pct, density, reason, scanned_at = fields
    return {
        "wallet": wallet,
        "label": WalletVerdict(label),
        "net": float(_field_value(net, "net")),
        "hedge": float(_field_value(hedge, "hedge")),
        "volume": int(_field_value(volume, "vol")),
        "market_trade_pct": float(_field_value(market_pct, "market_trade_pct")),
        "trade_density": float(_field_value(density, "trade_density")),
        "reason": reason,
        "scanned_at": scanned_at,
    }


def load_wallet_scan_report_rows(lines: Iterable[str]) -> list[WalletScanRecord]:
    rows = []
    for line_number, line in enumerate(lines, start=1):
        try:
            row = parse_wallet_scan_report_line(line)
        except ValueError as exc:
            print(
                f"line {line_number}: skipping unparseable line ({exc})",
                file=sys.stderr,
            )
            continue
        if row is not None:
            rows.append(row)
    return rows


def format_wallet_scan_record(
    *,
    label: WalletVerdict,
    net: float,
    hedge: float,
    volume: float,
    market_trade_pct: float,
    trade_density: float,
    reason: str,
    scanned_at: str,
) -> str:
    return (
        f"{label.value} net={net:+.2f} hedge={hedge:.2f} vol={volume:.0f} "
        f"market_trade_pct={market_trade_pct:.2f} "
        f"trade_density={trade_density:.2f} \"{reason}\" {scanned_at}"
    )


def _field_value(token: str, key: str) -> str:
    prefix = f"{key}="
    if not token.startswith(prefix):
        raise ValueError(f"expected token starting with {prefix!r}, got {token!r}")
    return token[len(prefix):]
