from dataclasses import asdict

import pytest

from scripts.wallet_analysis.contracts import WalletClassificationReason, WalletVerdict
from scripts.wallet_scan_report import (
    WalletScanRecord,
    WalletScanSortField,
    format_wallet_scan_record,
    parse_wallet_scan_report_line,
)


def test_scan_record_round_trip_and_sort_fields_preserve_types():
    record = WalletScanRecord(
        wallet="0x" + "a" * 40,
        label=WalletVerdict.GOOD,
        net_cash_usdc=12.5,
        hedge_score=0.1,
        traded_volume_usdc=20,
        market_trade_pct=75.0,
        trade_density=2.0,
        reason=WalletClassificationReason.NET_POSITIVE_DIRECTIONAL_REALIZED,
        scanned_at="2026-09-11T10:00:00Z",
    )
    fields = asdict(record)
    wallet = fields.pop("wallet")
    parsed = parse_wallet_scan_report_line(
        f"{wallet} {format_wallet_scan_record(**fields)}"
    )
    assert parsed == record
    assert parsed.sort_value(WalletScanSortField.NET) == record.net_cash_usdc
    assert parsed.sort_value(WalletScanSortField.VOLUME) == record.traded_volume_usdc
    assert parsed.sort_value(WalletScanSortField.WALLET) == record.wallet


@pytest.mark.parametrize("net_cash_usdc", ["NaN", "inf", "-inf"])
def test_scan_record_rejects_nonfinite_metrics(net_cash_usdc):
    line = f'wallet {WalletVerdict.BAD} net={net_cash_usdc} hedge=0.1 vol=20 market_trade_pct=75 trade_density=2 "{WalletClassificationReason.INCONCLUSIVE}" 2026-09-11T10:00:00Z'
    with pytest.raises(ValueError):
        parse_wallet_scan_report_line(line)
