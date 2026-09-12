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


def random_example() -> GraphExample:
    builder = ExampleBuilder()
    book_context_ref = ("book", GraphPort.CONTEXT)
    book_token_id_ref = ("book", BOOK_TOKEN_ID_PATH.handle_id)
    best_ask_handle_id = BOOK_BEST_ASK_PRICE_PATH.handle_id
    best_bid_handle_id = BOOK_BEST_BID_PRICE_PATH.handle_id
    builder.parameter("shares", "Order size (shares)", "5")
    builder.parameter("cooldown_ms", "Cooldown milliseconds", "5000")
    builder.parameter("probability", "Trade probability (0–1)", "0.5")
    builder.operation(
        "position",
        GraphOperation.POSITION,
        {GraphPort.CONTEXT: book_context_ref, GraphPort.TOKEN_ID: book_token_id_ref},
    )
    builder.operation(
        "flat",
        GraphOperation.NOT,
        {GraphPort.VALUE: ("position", GraphPort.HAS_POSITION)},
    )
    builder.operation(
        "quoted",
        GraphOperation.IS_PRESENT,
        {GraphPort.VALUE: ("book", best_ask_handle_id)},
    )
    builder.operation(
        "gate",
        GraphOperation.COOLDOWN,
        {
            GraphPort.CONTEXT: book_context_ref,
            GraphPort.ENABLED: ("quoted", GraphPort.RESULT),
            GraphPort.KEY: book_token_id_ref,
            GraphPort.DURATION_MS: ("cooldown_ms", GraphPort.VALUE),
        },
    )
    builder.operation(
        "random",
        GraphOperation.RANDOM_NUMBER,
        {
            GraphPort.CONTEXT: book_context_ref,
            GraphPort.ENABLED: ("gate", GraphPort.RESULT),
        },
    )
    builder.comparison(
        "trade",
        GraphComparisonOperator.LESS_THAN,
        ("random", GraphPort.VALUE),
        ("probability", GraphPort.VALUE),
    )
    builder.operation(
        "enter",
        GraphOperation.AND,
        {
            DEFAULT_BOOLEAN_INPUT_IDS[0]: ("flat", GraphPort.RESULT),
            DEFAULT_BOOLEAN_INPUT_IDS[1]: ("trade", GraphPort.RESULT),
        },
    )
    builder.action(
        "buy",
        GraphBrokerAction.SUBMIT_BUY,
        ("enter", GraphPort.RESULT),
        best_ask_handle_id,
        ("shares", GraphPort.VALUE),
    )
    builder.operation(
        "leave",
        GraphOperation.AND,
        {
            DEFAULT_BOOLEAN_INPUT_IDS[0]: ("position", GraphPort.HAS_POSITION),
            DEFAULT_BOOLEAN_INPUT_IDS[1]: ("trade", GraphPort.RESULT),
        },
    )
    builder.action(
        "sell",
        GraphBrokerAction.SUBMIT_SELL,
        ("leave", GraphPort.RESULT),
        best_bid_handle_id,
        ("position", GraphPort.SIZE),
    )
    return GraphExample(
        name="Random",
        description="Debug paper fills and charts: every 5 seconds per token, a 50% chance to buy while flat or sell held shares. Edit order size, cooldown and probability. Requires market updates; fills still depend on liquidity and paper limits.",
        graph=builder.graph(),
    )
