"""Exercise the selection policy against PostgreSQL JSONB and real LIMIT queries."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from api.database import async_database_url
from api.events.contracts import DURABLE_EVENT_ADAPTER
from api.events.ids import FIRST_EVENT_CURSOR
from api.events.kinds import EventKind
from api.events.models import EventRow
from api.events.schema import RUN_EVENTS_TABLE_NAME, EventColumn
from api.events.store import EventStore
from api.events.views import EventView, event_selection
from api.http.sse.frames import DASHBOARD_SSE_EVENT, event_frames
from api.runs.status import RunStatus
from polybot.cli.observability.states import BootstrapPhase
from polybot.execution.paper.portfolio import PAPER_SETTLEMENT_OWNER
from polybot.framework.activity import ActivitySeverity
from polybot.framework.events import FillRejectReason, OrderStatus, Side
from polybot.performance.contracts.valuation_status import ValuationStatus
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from control_plane.service_config import (
    POSTGRES_NOT_CONFIGURED_SKIP_REASON,
    TEST_POSTGRES_URL_ENV,
)


@pytest.mark.postgres
def test_history_and_replay_share_selection_before_pagination():
    url = os.getenv(TEST_POSTGRES_URL_ENV)
    if not url:
        pytest.skip(POSTGRES_NOT_CONFIGURED_SKIP_REASON)

    async def check():
        engine = create_async_engine(async_database_url(url))
        try:
            async with engine.connect() as connection:
                # A session-local table isolates this test from all retained run data.
                await connection.execute(
                    text(
                        f"CREATE TEMP TABLE {RUN_EVENTS_TABLE_NAME} ("
                        f"{EventColumn.ID} BIGINT PRIMARY KEY, {EventColumn.RUN_ID} UUID, "
                        f"{EventColumn.KIND} TEXT, {EventColumn.OCCURRED_AT} TIMESTAMPTZ, "
                        f"{EventColumn.PAYLOAD} JSONB)"
                    )
                )
                await connection.commit()
                async with AsyncSession(connection) as session:
                    run_id = uuid4()
                    rows = []
                    activity_ids = []
                    dashboard_ids = []
                    cases = tuple(_cases())
                    assert {case[0] for case in cases} == set(EventKind) - {
                        EventKind.WALLET_TIMELINE
                    }
                    for kind, payload, activity, dashboard in cases:
                        event = DURABLE_EVENT_ADAPTER.validate_python(
                            {
                                "run_id": run_id,
                                "occurred_at": datetime.now(UTC),
                                "kind": kind,
                                "payload": payload,
                            }
                        )
                        row = EventRow.from_event(event)
                        row.id = len(rows) + 1
                        rows.append(row)
                        if activity:
                            activity_ids.append(row.id)
                        if dashboard:
                            dashboard_ids.append(row.id)
                    # More routine skips than one page must not bury earlier outcomes.
                    for _ in range(150):
                        row = EventRow.from_event(
                            DURABLE_EVENT_ADAPTER.validate_python(
                                {
                                    "run_id": run_id,
                                    "occurred_at": datetime.now(UTC),
                                    "kind": EventKind.BOT_ACTIVITY,
                                    "payload": {
                                        "message": "Skipped: disabled",
                                        "severity": ActivitySeverity.INFO,
                                    },
                                }
                            )
                        )
                        row.id = len(rows) + 1
                        rows.append(row)
                    await session.execute(
                        insert(EventRow.__table__), [row.model_dump() for row in rows]
                    )
                    await session.commit()
                    store = EventStore(session)
                    for view, expected in (
                        (EventView.ACTIVITY, activity_ids),
                        (EventView.DASHBOARD, dashboard_ids),
                        (
                            EventView.DIAGNOSTICS,
                            [r.id for r in rows if r.kind != EventKind.CHART_SAMPLE],
                        ),
                    ):
                        before = None
                        restored = []
                        while True:
                            page = await store.read_page(
                                run_id, before_event_id=before, limit=2, view=view
                            )
                            assert page.stream_cursor == rows[-1].id
                            restored = [event.id for event in page.events] + restored
                            before = page.next_before_event_id
                            if before is None:
                                break
                        assert restored == expected
                        if view is EventView.DASHBOARD:
                            continue
                        deliveries = await store.read_deliveries(
                            run_id, after_event_id=FIRST_EVENT_CURSOR, view=view
                        )
                        assert [
                            d.event.id for d in deliveries if not d.dashboard_only
                        ] == expected
                        assert [d.event.id for d in deliveries] == sorted(
                            set(expected + dashboard_ids)
                        )
                        assert [
                            d.event.id for d in deliveries if d.dashboard_only
                        ] == sorted(set(dashboard_ids) - set(expected))
                        for delivery in deliveries:
                            frame = next(event_frames((delivery,)))[0]
                            assert (
                                f"event: {DASHBOARD_SSE_EVENT}\n" in frame
                            ) is delivery.dashboard_only
                        resumed = await store.read_deliveries(
                            run_id, after_event_id=deliveries[-1].event.id, view=view
                        )
                        assert resumed == ()
                    snapshot = await store.read_page(
                        run_id, before_event_id=None, limit=2
                    )
                    new_event = DURABLE_EVENT_ADAPTER.validate_python(
                        {
                            "run_id": run_id,
                            "occurred_at": datetime.now(UTC),
                            "kind": EventKind.RUN_FAILURE,
                            "payload": {"error": "Failure after hydration"},
                        }
                    )
                    new_row = EventRow.from_event(new_event)
                    new_row.id = rows[-1].id + 1
                    await session.execute(
                        insert(EventRow.__table__), new_row.model_dump()
                    )
                    await session.commit()
                    resumed = await store.read_deliveries(
                        run_id,
                        after_event_id=snapshot.stream_cursor,
                        view=EventView.ACTIVITY,
                    )
                    assert [delivery.event.id for delivery in resumed] == [new_row.id]
                    # Wallet classification depends only on kind; test the SQL rule
                    # independently from the existing wallet-payload serializer.
                    wallet_id = new_row.id + 1
                    await session.execute(
                        insert(EventRow.__table__),
                        {
                            "id": wallet_id,
                            "run_id": run_id,
                            "kind": EventKind.WALLET_TIMELINE,
                            "occurred_at": datetime.now(UTC),
                            "payload": {},
                        },
                    )
                    for view, expected in (
                        (EventView.ACTIVITY, False),
                        (EventView.DIAGNOSTICS, True),
                        (EventView.DASHBOARD, True),
                    ):
                        selected = await session.scalar(
                            select(event_selection(view)).where(
                                EventRow.id == wallet_id
                            )
                        )
                        assert selected is expected
                    # An unrelated run has neither rows nor a nonzero watermark.
                    empty = await store.read_page(
                        uuid4(), before_event_id=None, limit=2
                    )
                    assert (
                        empty.events == () and empty.stream_cursor == FIRST_EVENT_CURSOR
                    )
                    assert empty.next_before_event_id is None
        finally:
            await engine.dispose()

    asyncio.run(check())


def _cases():
    yield (
        EventKind.RUN_BOOTSTRAP,
        {
            "phase": BootstrapPhase.MARKETS,
            "completed": 1,
            "total": 1,
        },
        False,
        False,
    )
    for status in RunStatus:
        yield EventKind.RUN_LIFECYCLE, {"status": status}, True, False
    for severity in ActivitySeverity:
        yield (
            EventKind.BOT_ACTIVITY,
            {"message": "Diagnostic", "severity": severity},
            severity in (ActivitySeverity.WARNING, ActivitySeverity.ERROR),
            False,
        )
    order = {"token_id": "yes", "side": Side.BUY, "price": "0.5", "size": "5"}
    for status in OrderStatus:
        executed = status in (OrderStatus.FILLED, OrderStatus.PARTIAL)
        fill = {
            "order_id": "order",
            "token_id": "yes",
            "side": Side.BUY,
            "status": status,
            "requested_size": "5",
            "filled_size": "5"
            if status is OrderStatus.FILLED
            else "2"
            if executed
            else "0",
            "average_price": "0.5" if executed else None,
            "fee_usdc": "0",
            "received_at_ms": 1,
            "reject_reason": FillRejectReason.BAD_SIZE
            if status is OrderStatus.REJECTED
            else None,
            "reject_message": "Invalid size"
            if status is OrderStatus.REJECTED
            else None,
        }
        yield (
            EventKind.BROKER_FILL,
            {"order": order, "fill": fill, "portfolio": None, "latency_ms": 0},
            status is not OrderStatus.ACCEPTED,
            False,
        )
    yield EventKind.BROKER_ORDER, {"order": order}, False, False
    yield EventKind.BROKER_FAILURE, {"order": order, "error": "Failed"}, True, False
    yield EventKind.RUN_FAILURE, {"error": "Failed"}, True, False
    portfolio = {"cash_usdc": "100", "positions": [], "cumulative_fees_usdc": "0"}
    yield EventKind.PORTFOLIO_SNAPSHOT, portfolio, False, False
    yield (
        EventKind.CHART_SAMPLE,
        {
            "sampled_at_ms": 1,
            "markets": [],
            "equity": {"value": "100", "status": ValuationStatus.FRESH},
        },
        False,
        True,
    )
    yield (
        EventKind.STREAM_HEALTH,
        {
            "queue_depth": 0,
            "peak_queue_depth": 0,
            "book_dispatch_lag_ms": None,
            "book_stale": True,
            "book_received_count": 0,
            "book_coalesced_count": 0,
        },
        False,
        True,
    )
    for has_position in (False, True):
        settlement = {
            "resolution": {
                "condition_id": "condition",
                "market_slug": "market",
                "token_ids": ["yes", "no"],
                "winning_token_id": "yes",
                "winning_outcome": "Yes",
                "resolved_at_ms": 1,
                "source": "test",
            },
            "paper_positions": [
                {
                    "owner": PAPER_SETTLEMENT_OWNER,
                    "token_id": "no",
                    "size": "5",
                    "payout_per_token": "0",
                    "cash_payout_usdc": "0",
                }
            ]
            if has_position
            else [],
            "followed_wallet_positions": [],
            "settled_at_ms": 1,
        }
        yield (
            EventKind.MARKET_SETTLEMENT,
            {"settlement": settlement, "portfolio": portfolio},
            has_position,
            False,
        )
