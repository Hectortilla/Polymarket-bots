from decimal import Decimal
from datetime import datetime, timezone

from polymarket.models.data.activity import TradeActivity
from polymarket.models.data.portfolio import Position
from polymarket.models.gamma.market import Market

from polybot.framework.events import Side
from scripts.polymarket_wallet_api.sdk_payloads import activity_payload, market_payload, position_payload
from scripts.wallet_payloads import ACTIVITY_SIDE_FIELD, CONDITION_ID_FIELD, normalize_activity_rows, normalize_position_rows


def test_sdk_trade_model_normalizes_to_analysis_contract() -> None:
    model = TradeActivity.model_construct(
        wallet="0xwallet",
        timestamp=datetime.fromtimestamp(1, timezone.utc),
        transaction_hash="0xtx",
        type="TRADE",
        condition_id="condition",
        token_id="token",
        side="BUY",
        shares=Decimal("2"),
        amount=Decimal("0.8"),
        price=Decimal("0.4"),
        outcome="Yes",
        title="Question?",
        slug="market",
    )
    rows = normalize_activity_rows([activity_payload(model)])
    assert rows[0][CONDITION_ID_FIELD] == "condition"
    assert rows[0][ACTIVITY_SIDE_FIELD] == Side.BUY.value
    assert rows[0]["usdcSize"] == 0.8
    assert rows[0]["timestamp"] == 1


def test_sdk_position_model_normalizes_to_analysis_contract() -> None:
    model = Position.model_construct(
        wallet="0xwallet",
        condition_id="condition",
        size=Decimal("2"),
        current_value=Decimal("1"),
        realized_pnl=Decimal("0.2"),
        cash_pnl=Decimal("0.1"),
    )
    rows = normalize_position_rows([position_payload(model)])
    assert rows == [{
        "proxyWallet": "0xwallet",
        CONDITION_ID_FIELD: "condition",
        "size": 2.0,
        "currentValue": 1.0,
        "realizedPnl": 0.2,
        "cashPnl": 0.1,
    }]


def test_sdk_market_model_normalizes_condition_identifier() -> None:
    model = Market.model_construct(
        condition_id="condition",
        slug="market",
        question="Question?",
        state=None,
        schedule=None,
        resolution=None,
        outcomes=None,
    )
    assert market_payload(model)[CONDITION_ID_FIELD] == "condition"
