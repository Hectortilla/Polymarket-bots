from datetime import datetime, timezone
from decimal import Decimal

from polymarket.models.data.activity import TradeActivity
from polymarket.models.data.portfolio import Position
from polymarket.models.gamma.market import Market

from polybot.framework.events import Side
from polybot.framework.outcomes import YES_OUTCOME
from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TITLE_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
    POSITION_SIZE_FIELD,
    PROXY_WALLET_FIELD,
)
from scripts.polymarket_wallet_api.sdk_payloads import (
    activity_payload,
    market_payload,
    position_payload,
)
from scripts.wallet_payloads import (
    ACTIVITY_SIDE_FIELD,
    CONDITION_ID_FIELD,
    normalize_activity_rows,
    normalize_position_rows,
)


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
        outcome=YES_OUTCOME,
        title="Question?",
        slug="market",
    )
    rows = normalize_activity_rows([activity_payload(model)])
    assert rows == [{
        PROXY_WALLET_FIELD: "0xwallet",
        CONDITION_ID_FIELD: "condition",
        ACTIVITY_TRANSACTION_HASH_FIELD: "0xtx",
        ACTIVITY_TYPE_FIELD: "TRADE",
        ACTIVITY_TOKEN_ID_FIELD: "token",
        ACTIVITY_SIDE_FIELD: Side.BUY.value,
        ACTIVITY_SIZE_FIELD: 2.0,
        ACTIVITY_PRICE_FIELD: 0.4,
        ACTIVITY_USDC_SIZE_FIELD: 0.8,
        ACTIVITY_TIMESTAMP_FIELD: 1,
        ACTIVITY_OUTCOME_FIELD: YES_OUTCOME,
        ACTIVITY_TITLE_FIELD: "Question?",
        ACTIVITY_SLUG_FIELD: "market",
    }]


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
        PROXY_WALLET_FIELD: "0xwallet",
        CONDITION_ID_FIELD: "condition",
        POSITION_SIZE_FIELD: 2.0,
        POSITION_CURRENT_VALUE_FIELD: 1.0,
        POSITION_REALIZED_PNL_FIELD: 0.2,
        POSITION_CASH_PNL_FIELD: 0.1,
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
