from scripts.wallet_analysis import compute_metrics
from scripts.wallet_payloads import CONDITION_ID_FIELD, normalize_activity_rows, normalize_gamma_market, normalize_position_rows


def test_gamma_envelope_normalization_accepts_documented_list() -> None:
    assert normalize_gamma_market([{CONDITION_ID_FIELD: "condition"}]) == {CONDITION_ID_FIELD: "condition"}


def test_activity_normalization_rejects_unknown_trade_side() -> None:
    payload = [{"type": "TRADE", "side": "UNKNOWN", "size": 1, "price": 0.5, "usdcSize": 0.5}]
    assert normalize_activity_rows(payload) == []


def test_activity_normalization_rejects_nonfinite_financial_values() -> None:
    payload = [{"type": "TRADE", "side": "BUY", "size": "NaN", "price": 0.5, "usdcSize": 0.5}]
    assert normalize_activity_rows(payload) == []


def test_activity_normalization_rejects_out_of_range_trade_values() -> None:
    assert normalize_activity_rows(
        [{"type": "TRADE", "side": "SELL", "size": -1, "price": 1.1, "usdcSize": -1}]
    ) == []


def test_position_normalization_requires_nonnegative_size_and_value() -> None:
    assert normalize_position_rows(
        [{"size": -1, "currentValue": 1, "realizedPnl": 0, "cashPnl": 0}]
    ) == []


def test_wallet_metrics_use_only_normalized_trade_sides() -> None:
    activity = normalize_activity_rows(
        [{"type": "TRADE", "side": "BUY", "size": 2, "price": 0.4, "usdcSize": 0.8, "timestamp": 1}]
    )
    metrics = compute_metrics(activity, normalize_position_rows([]))
    assert metrics["net_cash"] == -0.8
    assert metrics["volume"] == 0.8
