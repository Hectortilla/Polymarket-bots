import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from polybot.framework.events import Side
from polybot.framework.outcomes import YES_OUTCOME
from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TITLE_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
)
from polybot.polymarket.wallet_reports.activity_payloads import activity_payload
from polybot.polymarket.wallet_reports.fields import (
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
    POSITION_SIZE_FIELD,
)
from polybot.polymarket.wallet_reports.gamma import (
    fetch_gamma_market,
    gamma_condition_id,
)
from polybot.polymarket.wallet_reports.market_payloads import market_payload
from polybot.polymarket.wallet_reports.normalization.activity import (
    normalize_activity_rows,
)
from polybot.polymarket.wallet_reports.normalization.positions import (
    normalize_position_rows,
)
from polybot.polymarket.wallet_reports.position_payloads import position_payload
from polymarket.models.data.activity import TradeActivity
from polymarket.models.data.portfolio import Position
from polymarket.models.gamma.market import Market
from sdk_market_fixture import sdk_market


def test_sdk_trade_model_normalizes_to_analysis_contract() -> None:
    model = TradeActivity.model_construct(
        wallet="0x" + "a" * 40,
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
    assert rows == [
        {
            PROXY_WALLET_FIELD: "0x" + "a" * 40,
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
        }
    ]


def test_sdk_position_model_normalizes_to_analysis_contract() -> None:
    model = Position.model_construct(
        wallet="0x" + "a" * 40,
        condition_id="condition",
        size=Decimal("2"),
        current_value=Decimal("1"),
        realized_pnl=Decimal("0.2"),
        cash_pnl=Decimal("0.1"),
    )
    rows = normalize_position_rows([position_payload(model)])
    assert rows == [
        {
            PROXY_WALLET_FIELD: "0x" + "a" * 40,
            CONDITION_ID_FIELD: "condition",
            POSITION_SIZE_FIELD: 2.0,
            POSITION_CURRENT_VALUE_FIELD: 1.0,
            POSITION_REALIZED_PNL_FIELD: 0.2,
            POSITION_CASH_PNL_FIELD: 0.1,
        }
    ]


def test_sdk_market_model_normalizes_condition_identifier() -> None:
    model = sdk_market("market")
    payload = market_payload(model)
    assert payload[CONDITION_ID_FIELD] == "condition-market"
    assert json.loads(json.dumps(payload)) == payload


def test_gamma_lookup_uses_the_shared_condition_identifier_contract() -> None:
    market = sdk_market("market")
    event = SimpleNamespace(
        slug="market",
        markets=[market],
        state=SimpleNamespace(closed=False),
    )
    client = _GammaClient(event, market)

    assert gamma_condition_id("market", client_factory=lambda: client) == (
        "condition-market",
        False,
    )
    assert fetch_gamma_market(
        "condition-market",
        client_factory=lambda: client,
    ) == market_payload(market)


class _GammaClient:
    def __init__(self, event: object, market: object) -> None:
        self.event = event
        self.market = market

    def __enter__(self) -> "_GammaClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_market(self, *, slug: str) -> Market:
        assert slug == self.market.slug
        return self.market

    def list_markets(self, **_: object) -> "_FirstPage":
        return _FirstPage(self.market)


class _FirstPage:
    def __init__(self, item: object) -> None:
        self.item = item

    def first_page(self) -> object:
        return SimpleNamespace(items=[self.item])
