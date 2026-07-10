#!/usr/bin/env python3
"""Parse a wallet-scan report into a list of dicts and sort by net P&L.

Expected line format (whitespace-separated, reason field quoted):
    <wallet> <label> net=<float> hedge=<float> vol=<int> market_trade_pct=<float> trade_density=<float> "<reason>" <scanned_at>
Lines starting with '#' (or blank) are treated as comments/headers and skipped.
"""

from __future__ import annotations

import sys

from scripts.wallet_scan_report import load_wallet_scan_report_rows

SORT_DESCENDING = True


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as fh:
            rows = load_wallet_scan_report_rows(fh)
    else:
        rows = load_wallet_scan_report_rows(sys.stdin)

    rows.sort(key=lambda r: r["net"], reverse=SORT_DESCENDING)

    for rank, row in enumerate(rows, start=1):
        print(
            f"{rank:>3}. {row['wallet']}  net={row['net']:+,.2f}  "
            f"hedge={row['hedge']:.2f}  vol={row['volume']:,}  "
            f"trade_density={row['trade_density']:.2f}  "
            f"{row['label']:<5}  {row['reason']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
