"""BaseBot lifecycle-hook discovery for graph trigger metadata."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import Parameter, iscoroutinefunction, signature
from typing import Any, get_type_hints

from polybot.framework.context import BotContext
from polybot_control_plane.catalog.graphs._fields import (
    DiscoveredGraphField,
    discover_graph_fields,
)
from polybot_control_plane.catalog.graphs.types import GRAPH_TRIGGER_HOOK_PREFIX


@dataclass(frozen=True, slots=True)
class DiscoveredGraphPayload:
    type_name: str
    fields: tuple[DiscoveredGraphField, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredGraphTrigger:
    hook_name: str
    payload: DiscoveredGraphPayload | None


def discover_graph_triggers(bot_type: type[Any]) -> tuple[DiscoveredGraphTrigger, ...]:
    return tuple(
        _discover_graph_trigger(hook_name, hook)
        for hook_name, hook in bot_type.__dict__.items()
        if hook_name.startswith(GRAPH_TRIGGER_HOOK_PREFIX)
        and iscoroutinefunction(hook)
    )


def _discover_graph_trigger(
    hook_name: str,
    hook: object,
) -> DiscoveredGraphTrigger:
    parameters = tuple(signature(hook).parameters.values())
    if len(parameters) not in {2, 3}:
        raise TypeError(
            f"graph trigger {hook_name} must accept self, BotContext, and at most one payload"
        )
    _require_positional_parameter(parameters[0], expected_name="self", hook_name=hook_name)
    _require_positional_parameter(parameters[1], expected_name=None, hook_name=hook_name)

    type_hints = get_type_hints(hook)
    context_parameter = parameters[1]
    if type_hints.get(context_parameter.name) is not BotContext:
        raise TypeError(f"graph trigger {hook_name} must annotate BotContext")
    if len(parameters) == 2:
        return DiscoveredGraphTrigger(hook_name=hook_name, payload=None)

    payload_parameter = parameters[2]
    _require_positional_parameter(payload_parameter, expected_name=None, hook_name=hook_name)
    payload_type = type_hints.get(payload_parameter.name)
    if not isinstance(payload_type, type):
        raise TypeError(f"graph trigger {hook_name} must annotate its payload type")
    return DiscoveredGraphTrigger(
        hook_name=hook_name,
        payload=DiscoveredGraphPayload(
            type_name=payload_type.__name__,
            fields=discover_graph_fields(payload_type),
        ),
    )


def _require_positional_parameter(
    parameter: Parameter,
    *,
    expected_name: str | None,
    hook_name: str,
) -> None:
    if parameter.kind not in {
        Parameter.POSITIONAL_ONLY,
        Parameter.POSITIONAL_OR_KEYWORD,
    }:
        raise TypeError(f"graph trigger {hook_name} parameters must be positional")
    if expected_name is not None and parameter.name != expected_name:
        raise TypeError(f"graph trigger {hook_name} must be an instance method")
