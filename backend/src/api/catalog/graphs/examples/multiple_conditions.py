from api.catalog.graphs.book_paths import (
    BOOK_BEST_ASK_PRICE_PATH,
    BOOK_TOKEN_ID_PATH,
)
from api.catalog.graphs.operations.logic import DEFAULT_BOOLEAN_INPUT_IDS
from api.catalog.graphs.values import (
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphOperation,
    GraphPort,
)

from .builder import ExampleBuilder
from .model import GraphExample
from .settings import (
    BUDGET_LABEL,
    DEFAULT_BUDGET,
    DEFAULT_ENTRY_THRESHOLD,
    ENTRY_THRESHOLD_LABEL,
)

FUNDING_CONDITION_INPUT = "input_3"


def multiple_conditions_example() -> GraphExample:
    builder = ExampleBuilder()
    builder.parameter("entry", ENTRY_THRESHOLD_LABEL, DEFAULT_ENTRY_THRESHOLD)
    builder.parameter("budget", BUDGET_LABEL, DEFAULT_BUDGET)
    builder.parameter("cooldown_ms", "Cooldown milliseconds", "1000")
    builder.operation(
        "cash", GraphOperation.BALANCE, {GraphPort.CONTEXT: ("book", GraphPort.CONTEXT)}
    )
    builder.operation(
        "position",
        GraphOperation.POSITION,
        {
            GraphPort.CONTEXT: ("book", GraphPort.CONTEXT),
            GraphPort.TOKEN_ID: (
                "book",
                BOOK_TOKEN_ID_PATH.handle_id,
            ),
        },
    )
    builder.operation(
        "flat",
        GraphOperation.NOT,
        {GraphPort.VALUE: ("position", GraphPort.HAS_POSITION)},
    )
    builder.comparison(
        "funded",
        GraphComparisonOperator.GREATER_THAN_OR_EQUAL,
        ("cash", GraphPort.AVAILABLE_CASH),
        ("budget", GraphPort.VALUE),
    )
    builder.comparison(
        "cheap",
        GraphComparisonOperator.LESS_THAN_OR_EQUAL,
        ("book", BOOK_BEST_ASK_PRICE_PATH.handle_id),
        ("entry", GraphPort.VALUE),
    )
    builder.operation(
        "conditions",
        GraphOperation.AND,
        {
            DEFAULT_BOOLEAN_INPUT_IDS[0]: ("flat", GraphPort.RESULT),
            DEFAULT_BOOLEAN_INPUT_IDS[1]: ("cheap", GraphPort.RESULT),
            FUNDING_CONDITION_INPUT: ("funded", GraphPort.RESULT),
        },
    )
    next(node for node in builder.nodes if node["id"] == "conditions")["data"][
        "input_ids"
    ] = [*DEFAULT_BOOLEAN_INPUT_IDS, FUNDING_CONDITION_INPUT]
    builder.operation(
        "gate",
        GraphOperation.COOLDOWN,
        {
            GraphPort.CONTEXT: ("book", GraphPort.CONTEXT),
            GraphPort.ENABLED: ("conditions", GraphPort.RESULT),
            GraphPort.KEY: ("book", BOOK_TOKEN_ID_PATH.handle_id),
            GraphPort.DURATION_MS: ("cooldown_ms", GraphPort.VALUE),
        },
    )
    builder.operation(
        "shares",
        GraphOperation.DIVIDE,
        {
            GraphPort.LEFT: ("budget", GraphPort.VALUE),
            GraphPort.RIGHT: (
                "book",
                BOOK_BEST_ASK_PRICE_PATH.handle_id,
            ),
        },
    )
    builder.action(
        "buy",
        GraphBrokerAction.SUBMIT_BUY,
        ("gate", GraphPort.RESULT),
        BOOK_BEST_ASK_PRICE_PATH.handle_id,
        ("shares", GraphPort.VALUE),
    )
    builder.operation(
        "explain",
        GraphOperation.LOG,
        {
            GraphPort.CONTEXT: ("book", GraphPort.CONTEXT),
            GraphPort.VALUE: ("buy", GraphPort.STATUS),
        },
    )
    return GraphExample(
        name="Multiple conditions and cooldown",
        description="Require a flat position, a cheap ask, sufficient cash, and a per-token cooldown; log the order outcome.",
        graph=builder.graph(),
    )
