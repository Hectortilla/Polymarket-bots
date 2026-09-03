"""Trusted broker-action discovery for the graph catalog."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from inspect import signature
from typing import get_type_hints

from polybot.execution.broker import Broker
from polybot.framework.events import FillEvent, OrderRequest, Side
from polybot_control_plane.catalog.graphs._annotations import (
    scalar_type_for_annotation,
    without_none,
)
from polybot_control_plane.catalog.graphs.values import (
    GRAPH_ACTION_ENABLED_HANDLE_ID,
    GRAPH_BROKER_SUBMIT_METHOD_NAME,
    GraphScalarType,
)


@dataclass(frozen=True, slots=True)
class DiscoveredActionInput:
    name: str
    scalar_type: GraphScalarType
    nullable: bool
    required: bool


@dataclass(frozen=True, slots=True)
class DiscoveredBrokerAction:
    method_name: str
    side: Side
    inputs: tuple[DiscoveredActionInput, ...]


def discover_broker_actions() -> tuple[DiscoveredBrokerAction, ...]:
    """Describe the sole explicitly allowed broker operation."""
    method = Broker.submit
    if method.__name__ != GRAPH_BROKER_SUBMIT_METHOD_NAME:
        raise TypeError("Broker.submit method name does not match the graph contract")
    parameters = tuple(signature(method).parameters.values())
    hints = get_type_hints(method)
    if (
        len(parameters) != 2
        or hints.get(parameters[1].name) is not OrderRequest
        or hints.get("return") is not FillEvent
    ):
        raise TypeError("Broker.submit must accept OrderRequest and return FillEvent")

    order_hints = get_type_hints(OrderRequest)
    order_fields = fields(OrderRequest)
    if order_hints.get("side") is not Side:
        raise TypeError("OrderRequest.side must use Side")
    inputs = (
        DiscoveredActionInput(
            name=GRAPH_ACTION_ENABLED_HANDLE_ID,
            scalar_type=GraphScalarType.BOOLEAN,
            nullable=False,
            required=True,
        ),
        *(
            _describe_order_input(field.name, order_hints[field.name], field.default)
            for field in order_fields
            if field.name != "side"
        ),
    )
    return tuple(
        DiscoveredBrokerAction(
            method_name=GRAPH_BROKER_SUBMIT_METHOD_NAME,
            side=side,
            inputs=inputs,
        )
        for side in Side
    )


def _describe_order_input(
    name: str,
    annotation: object,
    default: object,
) -> DiscoveredActionInput:
    value_annotation, nullable = without_none(annotation)
    scalar_type = scalar_type_for_annotation(value_annotation)
    if scalar_type is None:
        raise TypeError(f"unsupported broker action input type: {annotation}")
    return DiscoveredActionInput(
        name=name,
        scalar_type=scalar_type,
        nullable=nullable,
        required=default is MISSING,
    )
