"""Canonical Slice 12C HTTP route paths."""


API_PREFIX = "/api/v1"
BOT_DEFINITIONS_PATH = "/bot-definitions"
RUNS_PATH = "/runs"
RUN_PATH = "/runs/{run_id}"
RUN_STOP_PATH = "/runs/{run_id}/stop"
RUN_EVENTS_PATH = "/runs/{run_id}/events"
RUN_EVENTS_STREAM_PATH = "/runs/{run_id}/events/stream"
HEALTH_PATH = "/health"

LIST_BOT_DEFINITIONS_OPERATION_ID = (
    "list_bot_definitions_api_v1_bot_definitions_get"
)
LAUNCH_RUN_OPERATION_ID = "launch_run_api_v1_runs_post"
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
