from scripts.wallet_analysis.metrics import compute_metrics
from scripts.wallet_payloads import (
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
    POSITION_SIZE_FIELD,
    PROXY_WALLET_FIELD,
    normalize_activity_rows,
    normalize_gamma_market,
    normalize_position_rows,
)


def test_gamma_envelope_normalization_accepts_documented_list() -> None:
    assert normalize_gamma_market([{CONDITION_ID_FIELD: "condition"}]) == {CONDITION_ID_FIELD: "condition"}


def test_activity_normalization_rejects_unknown_trade_side() -> None:
    payload = _trade_payload(**{ACTIVITY_SIDE_FIELD: "UNKNOWN"})
    assert normalize_activity_rows(payload) == []


def test_activity_normalization_rejects_nonfinite_financial_values() -> None:
    payload = _trade_payload(**{ACTIVITY_SIZE_FIELD: "NaN"})
    assert normalize_activity_rows(payload) == []


def test_activity_normalization_rejects_out_of_range_trade_values() -> None:
    assert normalize_activity_rows(
        _trade_payload(
            **{
                ACTIVITY_SIDE_FIELD: "SELL",
                ACTIVITY_SIZE_FIELD: -1,
                ACTIVITY_PRICE_FIELD: 1.1,
                ACTIVITY_USDC_SIZE_FIELD: -1,
            }
        )
    ) == []


def test_position_normalization_requires_nonnegative_size_and_value() -> None:
    assert normalize_position_rows(
        [{
            PROXY_WALLET_FIELD: "0xwallet",
            CONDITION_ID_FIELD: "condition",
            POSITION_SIZE_FIELD: -1,
            POSITION_CURRENT_VALUE_FIELD: 1,
            POSITION_REALIZED_PNL_FIELD: 0,
            POSITION_CASH_PNL_FIELD: 0,
        }]
    ) == []


def test_wallet_metrics_use_only_normalized_trade_sides() -> None:
    activity = normalize_activity_rows(
        _trade_payload(
            **{
                ACTIVITY_SIZE_FIELD: 2,
                ACTIVITY_PRICE_FIELD: 0.4,
                ACTIVITY_USDC_SIZE_FIELD: 0.8,
                ACTIVITY_TIMESTAMP_FIELD: 1,
            }
        )
    )
    metrics = compute_metrics(activity, normalize_position_rows([]))
    assert metrics["net_cash"] == -0.8
    assert metrics["volume"] == 0.8


def test_activity_normalization_rejects_missing_trade_identity() -> None:
    payload = _trade_payload()
    payload[0].pop(ACTIVITY_TRANSACTION_HASH_FIELD)
    assert normalize_activity_rows(payload) == []


def _trade_payload(**overrides: object) -> list[dict[str, object]]:
    payload = {
        PROXY_WALLET_FIELD: "0xwallet",
        CONDITION_ID_FIELD: "condition",
        ACTIVITY_TRANSACTION_HASH_FIELD: "transaction",
        ACTIVITY_TOKEN_ID_FIELD: "token",
        ACTIVITY_TYPE_FIELD: "TRADE",
        ACTIVITY_SIDE_FIELD: "BUY",
        ACTIVITY_SIZE_FIELD: 1,
        ACTIVITY_PRICE_FIELD: 0.5,
        ACTIVITY_USDC_SIZE_FIELD: 0.5,
        ACTIVITY_TIMESTAMP_FIELD: 1,
    }
    payload.update(overrides)
    return [payload]
