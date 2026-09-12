from api.catalog.graphs.book_paths import (
    BOOK_BEST_ASK_PRICE_PATH,
    BOOK_BEST_BID_PRICE_PATH,
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


def entry_exit_example() -> GraphExample:
    builder = ExampleBuilder()
    builder.parameter("entry", ENTRY_THRESHOLD_LABEL, DEFAULT_ENTRY_THRESHOLD)
    builder.parameter("exit", "Exit threshold", "0.60")
    builder.parameter("budget", BUDGET_LABEL, DEFAULT_BUDGET)
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
        "cheap",
        GraphComparisonOperator.LESS_THAN_OR_EQUAL,
        ("book", BOOK_BEST_ASK_PRICE_PATH.handle_id),
        ("entry", GraphPort.VALUE),
    )
    builder.operation(
        "enter",
        GraphOperation.AND,
        {
            DEFAULT_BOOLEAN_INPUT_IDS[0]: ("flat", GraphPort.RESULT),
            DEFAULT_BOOLEAN_INPUT_IDS[1]: ("cheap", GraphPort.RESULT),
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
        ("enter", GraphPort.RESULT),
        BOOK_BEST_ASK_PRICE_PATH.handle_id,
        ("shares", GraphPort.VALUE),
    )
    builder.comparison(
        "expensive",
        GraphComparisonOperator.GREATER_THAN_OR_EQUAL,
        ("book", BOOK_BEST_BID_PRICE_PATH.handle_id),
        ("exit", GraphPort.VALUE),
    )
    builder.operation(
        "leave",
        GraphOperation.AND,
        {
            DEFAULT_BOOLEAN_INPUT_IDS[0]: ("position", GraphPort.HAS_POSITION),
            DEFAULT_BOOLEAN_INPUT_IDS[1]: ("expensive", GraphPort.RESULT),
        },
    )
    builder.action(
        "sell",
        GraphBrokerAction.SUBMIT_SELL,
        ("leave", GraphPort.RESULT),
        BOOK_BEST_BID_PRICE_PATH.handle_id,
        ("position", GraphPort.SIZE),
    )
    return GraphExample(
        name="Threshold entry and exit",
        description="Buy while flat below the entry threshold; sell the held position above the exit threshold. Budget is expressed in paper cash.",
        graph=builder.graph(),
    )
