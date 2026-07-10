from types import SimpleNamespace

from scripts import polymarket_wallet_api as api


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
            wallet="0xwallet", timestamp=index, transaction_hash=f"tx-{index}",
            type="TRADE", condition_id="condition", token_id="token", side="BUY",
            shares=1, amount=0.5, price=0.5, outcome="Yes", title="Question", slug="market",
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
    assert client.calls[0][1]["sort_by"] == api.ACTIVITY_SORT_BY


def test_market_position_workflow_flattens_sdk_envelopes(monkeypatch) -> None:
    position = SimpleNamespace(
        wallet="0xwallet", condition_id="condition", size=2,
        current_value=1, realized_pnl=0.2, cash_pnl=0.1,
    )
    client = FakeClient(market_positions=[SimpleNamespace(positions=(position,))])
    monkeypatch.setattr(api, "PublicClient", lambda: client)
    rows = api.fetch_market_positions("condition")
    assert rows[0]["size"] == 2.0
    assert client.calls[0][1]["status"] == api.MARKET_POSITION_STATUS
