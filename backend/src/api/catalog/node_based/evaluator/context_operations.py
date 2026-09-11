"""Graph reads of the event's immutable own-portfolio snapshot."""

from polybot.framework.portfolio import PortfolioSnapshot

from api.catalog.graphs.reasons import GraphReason
from api.catalog.graphs.values import GraphOperation, GraphPort
from api.catalog.node_based.evaluator.values import RuntimeValue


def portfolio_outputs(
    operation: GraphOperation,
    inputs: dict[str, RuntimeValue],
    snapshot: PortfolioSnapshot | None,
) -> dict[str, RuntimeValue]:
    names = (
        (GraphPort.AVAILABLE_CASH,)
        if operation is GraphOperation.BALANCE
        else (GraphPort.SIZE, GraphPort.HAS_POSITION, GraphPort.AVERAGE_ENTRY_PRICE)
    )
    unavailable = next(
        (value for value in inputs.values() if not value.available), None
    )
    if unavailable is not None:
        return dict.fromkeys(names, unavailable)
    if snapshot is None:
        return dict.fromkeys(
            names, RuntimeValue.skipped(GraphReason.PORTFOLIO_UNAVAILABLE)
        )
    if operation is GraphOperation.BALANCE:
        return {
            GraphPort.AVAILABLE_CASH: RuntimeValue.from_value(snapshot.available_cash)
        }
    position = snapshot.position(inputs[GraphPort.TOKEN_ID].value)
    return {
        GraphPort.SIZE: RuntimeValue.from_value(position.size),
        GraphPort.HAS_POSITION: RuntimeValue(position.size != 0),
        GraphPort.AVERAGE_ENTRY_PRICE: RuntimeValue.from_value(
            position.average_entry_price
        ),
    }
