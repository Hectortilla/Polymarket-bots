"""Backend-owned event selection shared by history and SSE replay."""

from enum import StrEnum

from polybot.framework.activity import ActivitySeverity
from polybot.framework.events import OrderStatus
from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from api.events.contracts.payloads.base import (
    ACTIVITY_SEVERITY_FIELD,
    BROKER_FILL_STATUS_PATH,
    SETTLEMENT_PAPER_POSITIONS_PATH,
)
from api.events.kinds import EventKind
from api.events.models import EventRow


class EventView(StrEnum):
    ACTIVITY = "activity"
    DIAGNOSTICS = "diagnostics"
    DASHBOARD = "dashboard"


DASHBOARD_EVENT_KINDS = (
    EventKind.CHART_SAMPLE,
    EventKind.WALLET_TIMELINE,
    EventKind.STREAM_HEALTH,
)


def event_selection(view: EventView) -> ColumnElement[bool]:
    """Filter stored rows before LIMIT; replay uses this exact predicate too."""
    if view is EventView.DASHBOARD:
        return EventRow.kind.in_(DASHBOARD_EVENT_KINDS)
    if view is EventView.DIAGNOSTICS:
        return EventRow.kind != EventKind.CHART_SAMPLE
    return or_(
        EventRow.kind.in_(
            (EventKind.RUN_LIFECYCLE, EventKind.RUN_FAILURE, EventKind.BROKER_FAILURE)
        ),
        and_(
            EventRow.kind == EventKind.BROKER_FILL,
            EventRow.payload[BROKER_FILL_STATUS_PATH].as_string()
            != OrderStatus.ACCEPTED,
        ),
        and_(
            EventRow.kind == EventKind.BOT_ACTIVITY,
            EventRow.payload[ACTIVITY_SEVERITY_FIELD]
            .as_string()
            .in_((ActivitySeverity.WARNING, ActivitySeverity.ERROR)),
        ),
        and_(
            EventRow.kind == EventKind.MARKET_SETTLEMENT,
            EventRow.payload[SETTLEMENT_PAPER_POSITIONS_PATH][0]
            .as_string()
            .is_not(None),
        ),
    )
