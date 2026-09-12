"""Canonical control-plane HTTP paths and operation identifiers."""

API_PREFIX = "/api/v1"
MARKET_SEARCH_PATH = "/markets/search"
MARKET_LOOKUP_PATH = "/markets/lookup"
SEARCH_MARKETS_OPERATION_ID = "search_markets"
LOOKUP_MARKETS_OPERATION_ID = "lookup_markets"
WALLET_SEARCH_PATH = "/wallets/search"
WALLET_LOOKUP_PATH = "/wallets/lookup"
SEARCH_WALLETS_OPERATION_ID = "search_wallets"
LOOKUP_WALLETS_OPERATION_ID = "lookup_wallets"
BOT_DEFINITIONS_PATH = "/bot-definitions"
BOTS_PATH = "/bots"
BOT_PATH = "/bots/{bot_id}"
BOT_RUNS_PATH = "/bots/{bot_id}/runs"
RUNS_PATH = "/runs"
RUN_PATH = "/runs/{run_id}"
RUN_STOP_PATH = "/runs/{run_id}/stop"
RUN_EVENTS_PATH = "/runs/{run_id}/events"
RUN_EVENTS_STREAM_PATH = "/runs/{run_id}/events/stream"
USAGE_PATH = "/usage"
READ_USAGE_OPERATION_ID = "read_usage"
HEALTH_PATH = "/health"

LIST_BOT_DEFINITIONS_OPERATION_ID = "list_bot_definitions_api_v1_bot_definitions_get"
CREATE_BOT_OPERATION_ID = "create_bot_api_v1_bots_post"
LIST_BOTS_OPERATION_ID = "list_bots_api_v1_bots_get"
READ_BOT_OPERATION_ID = "read_bot_api_v1_bots__bot_id__get"
DELETE_BOT_OPERATION_ID = "delete_bot_api_v1_bots__bot_id__delete"
UPDATE_BOT_OPERATION_ID = "update_bot_api_v1_bots__bot_id__patch"
LAUNCH_BOT_RUN_OPERATION_ID = "launch_bot_run_api_v1_bots__bot_id__runs_post"
LIST_RUNS_OPERATION_ID = "list_runs_api_v1_runs_get"
READ_RUN_OPERATION_ID = "read_run_api_v1_runs__run_id__get"
STOP_RUN_OPERATION_ID = "stop_run_api_v1_runs__run_id__stop_post"
READ_RUN_EVENTS_OPERATION_ID = "read_run_events_api_v1_runs__run_id__events_get"
STREAM_RUN_EVENTS_OPERATION_ID = (
    "stream_run_events_api_v1_runs__run_id__events_stream_get"
)
HEALTH_OPERATION_ID = "health_api_v1_health_get"


GRAPH_PREVIEW_PATH = "/graphs/preview"
PREVIEW_GRAPH_OPERATION_ID = "preview_graph"


def api_route_path(path: str, **parameters: object) -> str:
    resolved_path = path.format(**parameters) if parameters else path
    return f"{API_PREFIX}{resolved_path}"
