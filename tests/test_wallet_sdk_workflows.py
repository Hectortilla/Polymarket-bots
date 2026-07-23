from types import SimpleNamespace

from polymarket.errors import PolymarketError

from scripts import polymarket_wallet_api as api
from scripts.polymarket_wallet_api.constants import (
    ACTIVITY_SORT_BY,
    MARKET_POSITION_STATUS,
    MAX_ACTIVITY_OFFSET,
)
from scripts.wallet_payload_contracts import POSITION_SIZE_FIELD
from polybot.framework.outcomes import YES_OUTCOME


class FakePaginator:
    def __init__(self, items):
        self.items = tuple(items)

    def iter_items(self):
        yield from self.items

    def first_page(self):
        return SimpleNamespace(items=self.items)


class FakeClient:
    def __init__(self, *, activity=(), market_positions=()):
        self.activity = activity
        self.market_positions = market_positions
        self.calls = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def list_activity(self, **kwargs):
        self.calls.append(("activity", kwargs))
        return FakePaginator(self.activity)

    def list_market_positions(self, **kwargs):
        self.calls.append(("market_positions", kwargs))
        return FakePaginator(self.market_positions)


def test_fetch_activity_truncates_and_closes_sdk_client(monkeypatch) -> None:
    models = [
        SimpleNamespace(
            wallet="0xwallet",
            timestamp=index,
            transaction_hash=f"tx-{index}",
            type="TRADE",
            condition_id="condition",
            token_id="token",
            side="BUY",
            shares=1,
            amount=0.5,
            price=0.5,
            outcome=YES_OUTCOME,
            title="Question",
            slug="market",
        )
        for index in range(3)
    ]
    client = FakeClient(activity=models)
    monkeypatch.setattr(api, "PublicClient", lambda: client)
    monkeypatch.setattr(api, "enrich_activity_with_market_slug", lambda rows: rows)
    rows, truncated = api.fetch_all_activity("0xwallet", max_items=2)
    assert len(rows) == 2
    assert truncated is True
    assert client.closed is True
    assert client.calls[0][1]["sort_by"] == ACTIVITY_SORT_BY


def test_fetch_activity_keeps_rows_when_offset_limit_is_reached(monkeypatch) -> None:
    class OffsetLimitedPaginator(FakePaginator):
        def iter_items(self):
            yield from self.items
            raise PolymarketError(
                f"max historical activity offset of {MAX_ACTIVITY_OFFSET} exceeded"
            )

    models = [
        SimpleNamespace(
            wallet="0xwallet",
            timestamp=index,
            transaction_hash=f"tx-{index}",
            type="TRADE",
            condition_id="condition",
            token_id="token",
            side="BUY",
            shares=1,
            amount=0.5,
            price=0.5,
            outcome=YES_OUTCOME,
            title="Question",
            slug="market",
        )
        for index in range(2)
    ]
    client = FakeClient(activity=models)
    client.list_activity = lambda **kwargs: OffsetLimitedPaginator(models)
    monkeypatch.setattr(api, "PublicClient", lambda: client)
    monkeypatch.setattr(api, "enrich_activity_with_market_slug", lambda rows: rows)

    rows, truncated = api.fetch_all_activity("0xwallet", max_items=3)

    assert len(rows) == 2
    assert truncated is True


def test_market_position_workflow_flattens_sdk_envelopes(monkeypatch) -> None:
    position = SimpleNamespace(
        wallet="0xwallet",
        condition_id="condition",
        size=2,
        current_value=1,
        realized_pnl=0.2,
        cash_pnl=0.1,
    )
    client = FakeClient(market_positions=[SimpleNamespace(positions=(position,))])
    monkeypatch.setattr(api, "PublicClient", lambda: client)
    rows = api.fetch_market_positions("condition")
    assert rows[0][POSITION_SIZE_FIELD] == 2.0
    assert client.calls[0][1]["status"] == MARKET_POSITION_STATUS
