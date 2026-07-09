#!/usr/bin/env python3
"""Parse a wallet-scan report into a list of dicts and sort by net P&L.

Expected line format (whitespace-separated, reason field quoted):
    <wallet> <label> net=<float> hedge=<float> vol=<int> market_trade_pct=<float> trade_density=<float> "<reason>" <scanned_at>
Lines starting with '#' (or blank) are treated as comments/headers and skipped.
"""

from __future__ import annotations

import shlex
import sys

SORT_DESCENDING = True  # highest net first; flip to False for lowest-net-first


def _kv(token: str, key: str) -> str:
    prefix = f"{key}="
    if not token.startswith(prefix):
        raise ValueError(f"expected token starting with {prefix!r}, got {token!r}")
    return token[len(prefix):]


def parse_line(line: str) -> dict | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    wallet, label, net_tok, hedge_tok, vol_tok, market_pct_tok, density_tok, reason, scanned_at = shlex.split(line)

    return {
        "wallet": wallet,
        "label": label,
        "net": float(_kv(net_tok, "net")),
        "hedge": float(_kv(hedge_tok, "hedge")),
        "volume": int(_kv(vol_tok, "vol")),
        "market_trade_pct": float(_kv(market_pct_tok, "market_trade_pct")),
        "trade_density": float(_kv(density_tok, "trade_density")),
        "reason": reason,
        "scanned_at": scanned_at,
    }


def load_rows(lines) -> list[dict]:
    rows = []
    for lineno, raw_line in enumerate(lines, start=1):
        try:
            row = parse_line(raw_line)
        except ValueError as exc:
            print(f"line {lineno}: skipping unparseable line ({exc})", file=sys.stderr)
            continue
        if row is not None:
            rows.append(row)
    return rows


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as fh:
            rows = load_rows(fh)
    else:
        rows = load_rows(sys.stdin)

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
