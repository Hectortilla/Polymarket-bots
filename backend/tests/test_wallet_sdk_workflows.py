import json
from datetime import UTC, datetime
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from polybot.framework.outcomes import NO_OUTCOME, YES_OUTCOME
from polybot.polymarket.errors import MarketDataError
from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_TIMESTAMP_FIELD,
    CONDITION_ID_FIELD,
)
from polybot.polymarket.wallet_reports.activity import fetch_all_activity
from polybot.polymarket.wallet_reports.activity_contracts import (
    ACTIVITY_SORT_BY,
    MAX_ACTIVITY_OFFSET,
)
from polybot.polymarket.wallet_reports.contracts import POSITION_SIZE_FIELD
from polybot.polymarket.wallet_reports.errors import WalletReadError, WalletReadReason
from polybot.polymarket.wallet_reports.fields import ACTIVITY_TRUNCATED_FIELD
from polybot.polymarket.wallet_reports.gamma import (
    fetch_gamma_market,
    gamma_condition_id,
)
from polybot.polymarket.wallet_reports.market_contracts import (
    MARKET_OUTCOMES_FIELD,
    MARKET_START_DATE_FIELD,
)
from polybot.polymarket.wallet_reports.market_payloads import market_payload
from polybot.polymarket.wallet_reports.position_contracts import MARKET_POSITION_STATUS
from polybot.polymarket.wallet_reports.positions import (
    fetch_market_positions,
    fetch_positions,
)
from polymarket import RequestRejectedError
from polymarket.errors import PolymarketError
from polymarket.models.data.activity import TradeActivity
from polymarket.models.data.portfolio import Position
from sdk_market_fixture import sdk_market

from scripts.select_wallet_for_analysis import export as activity_export


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
            wallet="0x" + "a" * 40,
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
    rows, truncated = fetch_all_activity(
        "0x" + "a" * 40,
        max_items=2,
        client_factory=lambda: client,
        enrich=lambda rows: rows,
    )
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
            wallet="0x" + "a" * 40,
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

    rows, truncated = fetch_all_activity(
        "0x" + "a" * 40,
        max_items=3,
        client_factory=lambda: client,
        enrich=lambda rows: rows,
    )

    assert len(rows) == 2
    assert truncated is True


def test_market_position_workflow_flattens_sdk_envelopes(monkeypatch) -> None:
    position = SimpleNamespace(
        wallet="0x" + "a" * 40,
        condition_id="condition",
        size=2,
        current_value=1,
        realized_pnl=0.2,
        cash_pnl=0.1,
    )
    client = FakeClient(market_positions=[SimpleNamespace(positions=(position,))])
    rows = fetch_market_positions("condition", client_factory=lambda: client)
    assert rows[0][POSITION_SIZE_FIELD] == 2.0
    assert client.calls[0][1]["status"] == MARKET_POSITION_STATUS


def test_wallet_positions_use_all_pages() -> None:
    client = FakeClient()
    client.list_positions = lambda **kwargs: FakePaginator(
        (_position(), _position(size=3))
    )
    rows = fetch_positions("0x" + "a" * 40, client_factory=lambda: client)
    assert [row[POSITION_SIZE_FIELD] for row in rows] == [2.0, 3.0]
    assert client.closed


def _position(**changes):
    values = dict(
        wallet="0x" + "a" * 40,
        condition_id="condition",
        size=2,
        current_value=1,
        realized_pnl=0,
        cash_pnl=0,
    )
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"wallet": "bad"},
        {"wallet": "0x" + "b" * 40},
        {"size": float("nan")},
        {"condition_id": None},
        {"condition_id": 123},
    ],
)
def test_invalid_wallet_positions_fail_the_whole_read(changes) -> None:
    client = FakeClient()
    client.list_positions = lambda **kwargs: FakePaginator(
        (_position(), Position.model_construct(**vars(_position(**changes))))
    )
    with pytest.raises(WalletReadError) as caught:
        fetch_positions("0x" + "a" * 40, client_factory=lambda: client)
    assert caught.value.reason is WalletReadReason.INVALID_RESPONSE


@pytest.mark.parametrize("collection", [None, "malformed"])
def test_missing_market_positions_are_not_an_empty_success(collection) -> None:
    client = FakeClient(market_positions=(SimpleNamespace(positions=collection),))
    with pytest.raises(WalletReadError) as caught:
        fetch_market_positions("condition", client_factory=lambda: client)
    assert caught.value.reason is WalletReadReason.INVALID_RESPONSE


def test_position_transport_failure_is_not_an_empty_success() -> None:
    client = FakeClient()

    def failed_read(**kwargs):
        raise PolymarketError("vendor details")

    client.list_positions = failed_read
    with pytest.raises(WalletReadError) as caught:
        fetch_positions("0x" + "a" * 40, client_factory=lambda: client)
    assert caught.value.reason is WalletReadReason.UNAVAILABLE
    assert str(caught.value) == WalletReadReason.UNAVAILABLE.value
    assert client.closed


@pytest.mark.parametrize("wrong_slug", [False, True])
def test_gamma_exact_slug_uses_keyword_lookup_and_distinguishes_absence(wrong_slug):
    class Client(FakeClient):
        def get_market(self, *, slug):
            assert slug == "requested"
            if not wrong_slug:
                raise RequestRejectedError("missing", status=HTTPStatus.NOT_FOUND)
            return sdk_market("other")

    client = Client()
    if wrong_slug:
        with pytest.raises(WalletReadError) as caught:
            gamma_condition_id("requested", client_factory=lambda: client)
        assert caught.value.reason is WalletReadReason.INVALID_RESPONSE
    else:
        assert gamma_condition_id("requested", client_factory=lambda: client) == (
            None,
            None,
        )
    assert client.closed


def test_report_market_projection_is_json_safe_and_preserves_dates_and_labels():
    source = sdk_market("dated")
    started = datetime(2026, 1, 1, tzinfo=UTC)
    source = source.model_copy(
        update={"state": source.state.model_copy(update={"start_date": started})}
    )
    payload = market_payload(source)
    assert payload[MARKET_START_DATE_FIELD] == started.isoformat()
    assert payload[MARKET_OUTCOMES_FIELD] == [YES_OUTCOME, NO_OUTCOME]
    assert json.loads(json.dumps(payload)) == payload
    malformed = source.model_copy(
        update={
            "state": source.state.model_copy(
                update={"start_date": started.replace(tzinfo=None)}
            )
        }
    )
    with pytest.raises(MarketDataError):
        market_payload(malformed)


@pytest.mark.parametrize(
    "invalid_field, invalid_value",
    [
        ("wallet", "0x" + "b" * 40),
        ("price", float("nan")),
        ("condition_id", None),
        ("condition_id", 123),
        ("transaction_hash", None),
        ("transaction_hash", 123),
        ("token_id", None),
        ("token_id", 123),
        ("title", {}),
        ("slug", 123),
    ],
)
def test_bad_activity_row_invalidates_the_complete_report_read(
    invalid_field, invalid_value
):
    values = dict(
        wallet="0x" + "a" * 40,
        timestamp=1,
        transaction_hash="tx",
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
    valid = TradeActivity.model_construct(**values)
    values[invalid_field] = invalid_value
    client = FakeClient(activity=[valid, TradeActivity.model_construct(**values)])
    with pytest.raises(WalletReadError) as caught:
        fetch_all_activity(
            "0x" + "a" * 40, client_factory=lambda: client, enrich=lambda rows: rows
        )
    assert caught.value.reason is WalletReadReason.INVALID_RESPONSE


def test_activity_export_converts_market_dates_and_writes_json(monkeypatch, tmp_path):
    source = sdk_market("dated")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    source = source.model_copy(
        update={
            "state": source.state.model_copy(
                update={"start_date": start, "end_date": start}
            )
        }
    )
    payload = market_payload(source)
    row = {
        CONDITION_ID_FIELD: payload[CONDITION_ID_FIELD],
        ACTIVITY_TIMESTAMP_FIELD: int(start.timestamp()),
    }
    monkeypatch.setattr(activity_export, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(
        activity_export, "fetch_all_activity", lambda wallet: ([row], False)
    )
    monkeypatch.setattr(
        activity_export, "fetch_gamma_market", lambda condition: payload
    )
    path = activity_export.export_activity("0x" + "a" * 40)
    exported = json.loads(path.read_text())
    assert exported["market_context"][0]["market_start_timestamp"] == int(
        start.timestamp()
    )
    assert exported["activity"][0]["timestamp_ms"] == int(start.timestamp()) * 1000
    assert exported[ACTIVITY_TRUNCATED_FIELD] is False


def test_generic_activity_pagination_failure_rejects_partial_report():
    model = SimpleNamespace(
        wallet="0x" + "a" * 40,
        timestamp=1,
        transaction_hash="tx",
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

    class FailingPaginator(FakePaginator):
        def iter_items(self):
            yield from self.items
            raise PolymarketError("provider unavailable")

    client = FakeClient()
    client.list_activity = lambda **kwargs: FailingPaginator([model])
    enrich = Mock()
    with pytest.raises(WalletReadError) as caught:
        fetch_all_activity(model.wallet, client_factory=lambda: client, enrich=enrich)
    assert caught.value.reason is WalletReadReason.UNAVAILABLE
    assert isinstance(caught.value.__cause__, PolymarketError)
    assert client.closed
    enrich.assert_not_called()


@pytest.mark.parametrize("result_kind", ["empty", "conflicting", "wrong-condition"])
def test_gamma_condition_lookup_rejects_ambiguous_pages(result_kind):
    market = sdk_market("requested")
    if result_kind == "empty":
        models = []
    elif result_kind == "conflicting":
        models = [market, market.model_copy(update={"question": "Different question?"})]
    else:
        models = [sdk_market("other")]
    client = FakeClient()
    client.list_markets = lambda **kwargs: FakePaginator(models)
    if result_kind == "empty":
        assert (
            fetch_gamma_market(market.condition_id, client_factory=lambda: client)
            is None
        )
    else:
        with pytest.raises(WalletReadError) as caught:
            fetch_gamma_market(market.condition_id, client_factory=lambda: client)
        assert caught.value.reason is WalletReadReason.INVALID_RESPONSE
    assert client.closed
