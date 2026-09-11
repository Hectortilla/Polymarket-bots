from __future__ import annotations

import shlex
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from scripts.wallet_analysis.contracts import WalletClassificationReason, WalletVerdict

WALLET_SCAN_RECORD_FIELD_COUNT = 9


class WalletScanSortField(StrEnum):
    NET = "net"
    HEDGE = "hedge"
    VOLUME = "volume"
    MARKET_TRADE_PCT = "market_trade_pct"
    TRADE_DENSITY = "trade_density"
    SCANNED_AT = "scanned_at"
    WALLET = "wallet"


@dataclass(frozen=True, slots=True)
class WalletScanRecord:
    wallet: str
    label: WalletVerdict
    net_cash_usdc: float
    hedge_score: float
    traded_volume_usdc: int
    market_trade_pct: float
    trade_density: float
    reason: WalletClassificationReason
    scanned_at: str

    def sort_value(self, field: WalletScanSortField) -> float | int | str:
        return {
            WalletScanSortField.NET: self.net_cash_usdc,
            WalletScanSortField.HEDGE: self.hedge_score,
            WalletScanSortField.VOLUME: self.traded_volume_usdc,
            WalletScanSortField.MARKET_TRADE_PCT: self.market_trade_pct,
            WalletScanSortField.TRADE_DENSITY: self.trade_density,
            WalletScanSortField.SCANNED_AT: self.scanned_at,
            WalletScanSortField.WALLET: self.wallet,
        }[field]


def parse_wallet_scan_report_line(line: str) -> WalletScanRecord | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    fields = shlex.split(line)
    if len(fields) != WALLET_SCAN_RECORD_FIELD_COUNT:
        raise ValueError(
            f"expected {WALLET_SCAN_RECORD_FIELD_COUNT} fields, got {len(fields)}"
        )
    (
        wallet,
        label,
        net_cash_usdc,
        hedge_score,
        traded_volume_usdc,
        market_pct,
        density,
        reason,
        scanned_at,
    ) = fields
    record = WalletScanRecord(
        wallet=wallet,
        label=WalletVerdict(label),
        net_cash_usdc=float(_field_value(net_cash_usdc, "net")),
        hedge_score=float(_field_value(hedge_score, "hedge")),
        traded_volume_usdc=int(_field_value(traded_volume_usdc, "vol")),
        market_trade_pct=float(_field_value(market_pct, "market_trade_pct")),
        trade_density=float(_field_value(density, "trade_density")),
        reason=WalletClassificationReason(reason),
        scanned_at=scanned_at,
    )
    _validate_scan_record(record)
    return record


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
    net_cash_usdc: float,
    hedge_score: float,
    traded_volume_usdc: float,
    market_trade_pct: float,
    trade_density: float,
    reason: WalletClassificationReason,
    scanned_at: str,
) -> str:
    return (
        f"{label.value} net={net_cash_usdc:+.2f} hedge={hedge_score:.2f} vol={traded_volume_usdc:.0f} "
        f"market_trade_pct={market_trade_pct:.2f} "
        f'trade_density={trade_density:.2f} "{reason}" {scanned_at}'
    )


def _field_value(token: str, key: str) -> str:
    prefix = f"{key}="
    if not token.startswith(prefix):
        raise ValueError(f"expected token starting with {prefix!r}, got {token!r}")
    return token[len(prefix) :]


def _validate_scan_record(record: WalletScanRecord) -> None:
    numeric_values = (
        record.net_cash_usdc,
        record.hedge_score,
        float(record.traded_volume_usdc),
        record.market_trade_pct,
        record.trade_density,
    )
    if not all(isfinite(value) for value in numeric_values):
        raise ValueError("wallet scan numeric fields must be finite")
    if record.traded_volume_usdc < 0 or record.trade_density < 0:
        raise ValueError("wallet scan volume and density must be nonnegative")
    if not 0 <= record.hedge_score <= 1:
        raise ValueError("wallet scan hedge must be between 0 and 1")
    if not 0 <= record.market_trade_pct <= 100:
        raise ValueError("wallet scan market_trade_pct must be between 0 and 100")
