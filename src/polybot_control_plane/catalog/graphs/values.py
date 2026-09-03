"""Dependency-light graph constants and finite value sets."""

from enum import StrEnum


MIN_GRAPH_IDENTIFIER_LENGTH = 1
MIN_GRAPH_FIELD_PATH_SEGMENTS = 1
MIN_GRAPH_INPUT_SCALAR_TYPES = 1
MAX_GRAPH_IDENTIFIER_LENGTH = 64
MAX_GRAPH_EDGE_IDENTIFIER_LENGTH = 320
NODE_GRAPH_COORDINATE_LIMIT = 10_000
GRAPH_ACTION_ENABLED_HANDLE_ID = "enabled"
GRAPH_BROKER_SUBMIT_METHOD_NAME = "submit"
GRAPH_CONTEXT_HANDLE_ID = "context"
GRAPH_CONTEXT_TYPE_NAME = "BotContext"
GRAPH_FIELD_HANDLE_PREFIX = "field:"
GRAPH_FIELD_PATH_SEPARATOR = "."
GRAPH_FIELD_PATH_SEGMENT_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
GRAPH_VALUE_HANDLE_ID = "value"
GRAPH_COMPARISON_LEFT_HANDLE_ID = "left"
GRAPH_COMPARISON_RIGHT_HANDLE_ID = "right"
GRAPH_COMPARISON_RESULT_HANDLE_ID = "result"
GRAPH_TRIGGER_HOOK_PREFIX = "on_"
GRAPH_HOOK_NAME_PATTERN = rf"^{GRAPH_TRIGGER_HOOK_PREFIX}[a-z][a-z0-9_]*$"


class GraphNodeType(StrEnum):
    TRIGGER = "trigger"
    CONSTANT = "constant"
    COMPARISON = "comparison"
    BROKER_ACTION = "broker_action"


class GraphComparisonOperator(StrEnum):
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"


class GraphBrokerAction(StrEnum):
    SUBMIT_BUY = "submit_buy"
    SUBMIT_SELL = "submit_sell"


class GraphScalarType(StrEnum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    STRING = "string"
