"""Generate frontend runtime constants from the backend run contract."""

from __future__ import annotations

import json
from pathlib import Path

from polybot.dashboard.contracts import (
    DashboardKey,
    BucketRounding,
    CHART_WINDOW_CLAMP_MAXIMUM,
    CHART_WINDOW_CLAMP_MINIMUM,
    CHART_WINDOW_ROUNDING,
    INITIAL_TIME_ZOOM_LEVEL,
    FIRST_WALLET_NOTIONAL_TIER,
    MAX_CHART_HISTORY_POINTS,
    MAX_CHART_TOKENS,
    MAX_TIME_ZOOM_LEVEL,
    MAX_WALLET_TIMELINE_EVENTS,
    MARKET_LABEL_PART_SEPARATOR,
    MIN_TIME_ZOOM_LEVEL,
    NONPOSITIVE_MAX_NOTIONAL_THRESHOLD,
    TIME_ZOOM_FACTOR,
    TOKEN_LABEL_ELLIPSIS,
    TOKEN_LABEL_MAXIMUM_LENGTH,
    TOKEN_LABEL_PREFIX_LENGTH,
    TOKEN_LABEL_SUFFIX_LENGTH,
    WALLET_NOTIONAL_TIER_COUNT,
    WALLET_NOTIONAL_TIER_DENOMINATOR,
    WALLET_NOTIONAL_TIER_UPPER_NUMERATORS,
    WALLET_BUCKET_CLAMP_TO_LAST_COLUMN,
    WALLET_BUCKET_ROUNDING,
    WALLET_NOTIONAL_TIER_UPPER_BOUND_INCLUSIVE,
)
from polybot.cli.observability.states import (
    BOOTSTRAP_COMPLETED_MAY_EXCEED_TOTAL,
    BOOTSTRAP_PROGRESS_MINIMUM,
    BootstrapPhase,
)
from polybot.framework.activity import ActivitySeverity
from polybot.framework.config.constants import (
    MAX_DATA_TRADES_PER_RATE_LIMIT_WINDOW,
    MIN_DATA_TRADES_PER_RATE_LIMIT_WINDOW,
)
from polybot.framework.config.mode import BotMode
from polybot.framework.dispatch import (
    DISPATCH_ACCEPTED_OUTCOME_ALLOWS_SKIP_REASON,
    DISPATCH_SKIPPED_OUTCOME_REQUIRES_SKIP_REASON,
    DispatchSkipReason,
)
from polybot.framework.events import (
    FILL_EXECUTION_SIZE_FLOOR,
    FILL_STATUS_POLICIES,
    FillExecutionConstraint,
    FillRejectReason,
    OrderStatus,
    Side,
)
from polybot.framework.events.prices import (
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
    is_outcome_payout,
    is_outcome_price,
)
from polybot.framework.events.resolution_tokens import MARKET_RESOLUTION_TOKEN_COUNT
from polybot.framework.events.wallet_trades import (
    WALLET_SOURCE_KEY_SEPARATOR,
    WalletTradeKind,
)
from polybot.framework.streams import (
    STREAM_RULE_MINIMUM_SELECTOR_GROUPS,
    StreamRelation,
)
from polybot.framework.wallets import WALLET_ADDRESS_SCHEMA_PATTERN
from polybot.performance.contracts.valuation_status import ValuationStatus
from polybot_control_plane.api.routes.paths import (
    BOT_DEFINITIONS_PATH,
    BOT_GRAPH_REVISION_PATH,
    BOT_GRAPH_REVISIONS_PATH,
    BOT_PATH,
    BOT_RUNS_PATH,
    BOTS_PATH,
    GRAPH_TEMPLATE_PATH,
    GRAPH_TEMPLATES_PATH,
    HEALTH_PATH,
    RUN_EVENTS_PATH,
    RUN_EVENTS_STREAM_PATH,
    RUN_PATH,
    RUN_STOP_PATH,
    RUNS_PATH,
    api_route_path,
)
from polybot_control_plane.api.contracts import HealthResponse
from polybot_control_plane.events.ids import (
    FIRST_DURABLE_EVENT_ID,
    FIRST_EVENT_CURSOR,
    MAX_DURABLE_EVENT_ID,
)
from polybot_control_plane.events.pagination import NEXT_EVENT_PAGE_CURSOR_EVENT_INDEX
from polybot_control_plane.bots.revisions import FIRST_GRAPH_REVISION_NUMBER
from polybot_control_plane.events.kinds import EventKind, LiveEventKind
from polybot_control_plane.events.contracts.payloads import (
    CHART_NULL_VALUE_STATUSES,
    CHART_VALUE_REQUIRED_STATUSES,
    PORTFOLIO_EMPTY_POSITION_REQUIRES_NULL_PRICE,
    PORTFOLIO_MINIMUM_CUMULATIVE_FEES,
    PORTFOLIO_MINIMUM_POSITION_SIZE,
    PORTFOLIO_TOKEN_IDS_MUST_BE_UNIQUE,
)
from polybot_control_plane.runs.status import (
    INITIAL_RUN_STATUS,
    STOPPABLE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    RunStatus,
)


FRONTEND_RUN_CONTRACT_PATH = (
    Path(__file__).parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "runtimeContract.fixture.json"
)


def frontend_run_contract() -> dict[str, object]:
    return {
        "activitySeverity": _enum_values(ActivitySeverity),
        "apiPaths": {
            "botDefinitions": api_route_path(BOT_DEFINITIONS_PATH),
            "botGraphRevision": api_route_path(BOT_GRAPH_REVISION_PATH),
            "botGraphRevisions": api_route_path(BOT_GRAPH_REVISIONS_PATH),
            "bot": api_route_path(BOT_PATH),
            "botRuns": api_route_path(BOT_RUNS_PATH),
            "bots": api_route_path(BOTS_PATH),
            "graphTemplate": api_route_path(GRAPH_TEMPLATE_PATH),
            "graphTemplates": api_route_path(GRAPH_TEMPLATES_PATH),
            "health": api_route_path(HEALTH_PATH),
            "runEvents": api_route_path(RUN_EVENTS_PATH),
            "runEventsStream": api_route_path(RUN_EVENTS_STREAM_PATH),
            "run": api_route_path(RUN_PATH),
            "runStop": api_route_path(RUN_STOP_PATH),
            "runs": api_route_path(RUNS_PATH),
        },
        "botMode": _enum_values(BotMode),
        "config": {
            "maximumDataTradesBudget": MAX_DATA_TRADES_PER_RATE_LIMIT_WINDOW,
            "minimumDataTradesBudget": MIN_DATA_TRADES_PER_RATE_LIMIT_WINDOW,
        },
        "bootstrapPhase": _enum_values(BootstrapPhase),
        "bootstrapProgress": {
            "completedMayExceedTotal": BOOTSTRAP_COMPLETED_MAY_EXCEED_TOTAL,
            "minimum": BOOTSTRAP_PROGRESS_MINIMUM,
        },
        "dashboard": {
            "initialTimeZoomLevel": INITIAL_TIME_ZOOM_LEVEL,
            "keys": _enum_values(DashboardKey),
            "maxChartHistoryPoints": MAX_CHART_HISTORY_POINTS,
            "maxChartTokens": MAX_CHART_TOKENS,
            "maxTimeZoomLevel": MAX_TIME_ZOOM_LEVEL,
            "maxWalletTimelineEvents": MAX_WALLET_TIMELINE_EVENTS,
            "minTimeZoomLevel": MIN_TIME_ZOOM_LEVEL,
            "timeZoomFactor": TIME_ZOOM_FACTOR,
            "chartWindowPolicy": {
                "clampMaximum": CHART_WINDOW_CLAMP_MAXIMUM,
                "clampMinimum": CHART_WINDOW_CLAMP_MINIMUM,
                "rounding": CHART_WINDOW_ROUNDING.value,
            },
            "walletNotionalTierCount": WALLET_NOTIONAL_TIER_COUNT,
            "firstWalletNotionalTier": FIRST_WALLET_NOTIONAL_TIER,
            "nonpositiveMaxNotionalThreshold": str(
                NONPOSITIVE_MAX_NOTIONAL_THRESHOLD
            ),
            "walletNotionalTierDenominator": WALLET_NOTIONAL_TIER_DENOMINATOR,
            "walletNotionalTierUpperNumerators": list(
                WALLET_NOTIONAL_TIER_UPPER_NUMERATORS
            ),
            "walletBucketPolicy": {
                "clampToLastColumn": WALLET_BUCKET_CLAMP_TO_LAST_COLUMN,
                "rounding": WALLET_BUCKET_ROUNDING.value,
            },
            "walletBucketRounding": _enum_values(BucketRounding),
            "walletNotionalTierUpperBoundInclusive": (
                WALLET_NOTIONAL_TIER_UPPER_BOUND_INCLUSIVE
            ),
            "walletMarketLabelPolicy": {
                "ellipsis": TOKEN_LABEL_ELLIPSIS,
                "maximumTokenLength": TOKEN_LABEL_MAXIMUM_LENGTH,
                "partSeparator": MARKET_LABEL_PART_SEPARATOR,
                "prefixLength": TOKEN_LABEL_PREFIX_LENGTH,
                "suffixLength": TOKEN_LABEL_SUFFIX_LENGTH,
            },
        },
        "dispatchSkipReason": {
            reason.name: reason.value for reason in DispatchSkipReason
        },
        "dispatchOutcome": {
            "acceptedAllowsSkipReason": (
                DISPATCH_ACCEPTED_OUTCOME_ALLOWS_SKIP_REASON
            ),
            "skippedRequiresSkipReason": (
                DISPATCH_SKIPPED_OUTCOME_REQUIRES_SKIP_REASON
            ),
        },
        "durableEventIds": {
            "firstCursor": FIRST_EVENT_CURSOR,
            "firstEventId": FIRST_DURABLE_EVENT_ID,
            "maximumEventId": MAX_DURABLE_EVENT_ID,
        },
        "eventPagination": {
            "nextCursorEventIndex": NEXT_EVENT_PAGE_CURSOR_EVENT_INDEX,
        },
        "eventKind": _enum_values(EventKind),
        "fillRejectReason": _enum_values(FillRejectReason),
        "fillExecutionConstraint": _enum_values(FillExecutionConstraint),
        "fillExecution": {
            "minimumExclusiveSize": str(FILL_EXECUTION_SIZE_FLOOR),
        },
        "fillStatusPolicy": {
            status.value: {
                "execution": policy.execution.value,
                "requiresRejectDetails": policy.requires_reject_details,
            }
            for status, policy in FILL_STATUS_POLICIES.items()
        },
        "healthStatus": HealthResponse().status,
        "minimumGraphRevisionNumber": FIRST_GRAPH_REVISION_NUMBER,
        "marketResolution": {
            "tokenCount": MARKET_RESOLUTION_TOKEN_COUNT,
        },
        "chartValueStatus": {
            "nullValue": sorted(status.value for status in CHART_NULL_VALUE_STATUSES),
            "valueRequired": sorted(
                status.value for status in CHART_VALUE_REQUIRED_STATUSES
            ),
        },
        "portfolio": {
            "emptyPositionRequiresNullPrice": (
                PORTFOLIO_EMPTY_POSITION_REQUIRES_NULL_PRICE
            ),
            "minimumCumulativeFees": str(PORTFOLIO_MINIMUM_CUMULATIVE_FEES),
            "minimumPositionSize": str(PORTFOLIO_MINIMUM_POSITION_SIZE),
            "tokenIdsMustBeUnique": PORTFOLIO_TOKEN_IDS_MUST_BE_UNIQUE,
        },
        "liveEventKind": _enum_values(LiveEventKind),
        "orderStatus": _enum_values(OrderStatus),
        "outcomePrice": {
            "ceiling": str(OUTCOME_PRICE_CEILING),
            "floor": str(OUTCOME_PRICE_FLOOR),
            "includeFloor": is_outcome_price(OUTCOME_PRICE_FLOOR),
        },
        "outcomePayout": {
            "ceiling": str(OUTCOME_PRICE_CEILING),
            "floor": str(OUTCOME_PRICE_FLOOR),
            "includeFloor": is_outcome_payout(OUTCOME_PRICE_FLOOR),
        },
        "runStatus": {
            "initial": INITIAL_RUN_STATUS.value,
            "stoppable": sorted(status.value for status in STOPPABLE_RUN_STATUSES),
            "terminal": sorted(status.value for status in TERMINAL_RUN_STATUSES),
            "values": _enum_values(RunStatus),
        },
        "side": _enum_values(Side),
        "streamRelation": _enum_values(StreamRelation),
        "streamRule": {
            "minimumSelectorGroups": {
                relation.value: minimum
                for relation, minimum in STREAM_RULE_MINIMUM_SELECTOR_GROUPS.items()
            },
        },
        "valuationStatus": _enum_values(ValuationStatus),
        "walletTradeKind": _enum_values(WalletTradeKind),
        "walletSourceKeySeparator": WALLET_SOURCE_KEY_SEPARATOR,
        "walletAddressPattern": WALLET_ADDRESS_SCHEMA_PATTERN,
    }


def _enum_values(enum_type: type) -> dict[str, str]:
    return {item.name: item.value for item in enum_type}


def write_frontend_run_contract() -> None:
    FRONTEND_RUN_CONTRACT_PATH.write_text(
        json.dumps(frontend_run_contract(), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_frontend_run_contract()
