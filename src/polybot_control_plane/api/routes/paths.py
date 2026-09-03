"""Canonical control-plane HTTP paths and operation identifiers."""

API_PREFIX = "/api/v1"
BOT_DEFINITIONS_PATH = "/bot-definitions"
GRAPH_TEMPLATES_PATH = "/graph-templates"
GRAPH_TEMPLATE_PATH = "/graph-templates/{template_id}"
BOTS_PATH = "/bots"
BOT_PATH = "/bots/{bot_id}"
BOT_GRAPH_REVISIONS_PATH = "/bots/{bot_id}/graph-revisions"
BOT_GRAPH_REVISION_PATH = "/bots/{bot_id}/graph-revisions/{revision_id}"
BOT_RUNS_PATH = "/bots/{bot_id}/runs"
RUNS_PATH = "/runs"
RUN_PATH = "/runs/{run_id}"
RUN_STOP_PATH = "/runs/{run_id}/stop"
RUN_EVENTS_PATH = "/runs/{run_id}/events"
RUN_EVENTS_STREAM_PATH = "/runs/{run_id}/events/stream"
HEALTH_PATH = "/health"

LIST_BOT_DEFINITIONS_OPERATION_ID = "list_bot_definitions_api_v1_bot_definitions_get"
CREATE_GRAPH_TEMPLATE_OPERATION_ID = "create_graph_template_api_v1_graph_templates_post"
LIST_GRAPH_TEMPLATES_OPERATION_ID = "list_graph_templates_api_v1_graph_templates_get"
READ_GRAPH_TEMPLATE_OPERATION_ID = (
    "read_graph_template_api_v1_graph_templates__template_id__get"
)
UPDATE_GRAPH_TEMPLATE_OPERATION_ID = (
    "update_graph_template_api_v1_graph_templates__template_id__patch"
)
CREATE_BOT_OPERATION_ID = "create_bot_api_v1_bots_post"
LIST_BOTS_OPERATION_ID = "list_bots_api_v1_bots_get"
READ_BOT_OPERATION_ID = "read_bot_api_v1_bots__bot_id__get"
UPDATE_BOT_OPERATION_ID = "update_bot_api_v1_bots__bot_id__patch"
CREATE_BOT_GRAPH_REVISION_OPERATION_ID = (
    "create_bot_graph_revision_api_v1_bots__bot_id__graph_revisions_post"
)
READ_BOT_GRAPH_REVISION_OPERATION_ID = (
    "read_bot_graph_revision_api_v1_bots__bot_id__graph_revisions__revision_id__get"
)
LAUNCH_BOT_RUN_OPERATION_ID = "launch_bot_run_api_v1_bots__bot_id__runs_post"
LIST_RUNS_OPERATION_ID = "list_runs_api_v1_runs_get"
READ_RUN_OPERATION_ID = "read_run_api_v1_runs__run_id__get"
STOP_RUN_OPERATION_ID = "stop_run_api_v1_runs__run_id__stop_post"
READ_RUN_EVENTS_OPERATION_ID = "read_run_events_api_v1_runs__run_id__events_get"
STREAM_RUN_EVENTS_OPERATION_ID = (
    "stream_run_events_api_v1_runs__run_id__events_stream_get"
)
HEALTH_OPERATION_ID = "health_api_v1_health_get"


def api_route_path(path: str, **parameters: object) -> str:
    resolved_path = path.format(**parameters) if parameters else path
    return f"{API_PREFIX}{resolved_path}"
