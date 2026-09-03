"""Dataclass field discovery for graph trigger payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from inspect import Parameter, signature
from typing import Any, get_args, get_origin, get_type_hints

from pydantic import TypeAdapter

from polybot.framework.graph import is_graph_output
from polybot_control_plane.catalog.graphs._annotations import (
    scalar_type_for_annotation,
    without_none,
)
from polybot_control_plane.catalog.graphs.values import GraphScalarType


COLLECTION_ORIGINS = frozenset({list, tuple})


@dataclass(frozen=True, slots=True)
class DiscoveredGraphField:
    path: tuple[str, ...]
    value_type: str
    scalar_type: GraphScalarType | None
    nullable: bool
    collection: bool
    value_schema: Mapping[str, object]


def discover_graph_fields(payload_type: type[Any]) -> tuple[DiscoveredGraphField, ...]:
    if not is_dataclass(payload_type):
        raise TypeError("graph trigger payloads must be dataclass types")
    return (
        *_discover_dataclass_fields(payload_type, path_prefix=()),
        *_discover_computed_fields(payload_type),
    )


def _discover_dataclass_fields(
    payload_type: type[Any],
    *,
    path_prefix: tuple[str, ...],
    parent_nullable: bool = False,
) -> tuple[DiscoveredGraphField, ...]:
    type_hints = get_type_hints(payload_type)
    discovered: list[DiscoveredGraphField] = []
    for field in fields(payload_type):
        annotation = type_hints[field.name]
        path = (*path_prefix, field.name)
        value_type, nullable, collection, nested_type = _describe_annotation(annotation)
        nullable = parent_nullable or nullable
        discovered.append(
            DiscoveredGraphField(
                path=path,
                value_type=value_type,
                scalar_type=scalar_type_for_annotation(annotation),
                nullable=nullable,
                collection=collection,
                value_schema=TypeAdapter(annotation).json_schema(),
            )
        )
        if nested_type is not None and not collection:
            discovered.extend(
                _discover_dataclass_fields(
                    nested_type,
                    path_prefix=path,
                    parent_nullable=nullable,
                )
            )
    return tuple(discovered)


def _discover_computed_fields(
    payload_type: type[Any],
) -> tuple[DiscoveredGraphField, ...]:
    discovered: list[DiscoveredGraphField] = []
    for name, value in payload_type.__dict__.items():
        if not is_graph_output(value):
            continue
        getter = value.fget
        if getter is None:
            continue
        parameters = tuple(signature(getter).parameters.values())
        if len(parameters) != 1 or parameters[0].kind not in {
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
        }:
            raise TypeError(
                f"graph output {payload_type.__name__}.{name} must take no arguments"
            )
        annotation = get_type_hints(getter).get("return")
        if annotation is None:
            raise TypeError(
                f"graph output {payload_type.__name__}.{name} must annotate its return"
            )
        _, nullable, collection, nested_type = _describe_annotation(annotation)
        if collection or nested_type is None:
            raise TypeError(
                f"graph output {payload_type.__name__}.{name} must return a dataclass"
            )
        discovered.extend(
            _discover_dataclass_fields(
                nested_type,
                path_prefix=(name,),
                parent_nullable=nullable,
            )
        )
    return tuple(discovered)


def _describe_annotation(
    annotation: object,
) -> tuple[str, bool, bool, type[Any] | None]:
    value_annotation, nullable = without_none(annotation)
    origin = get_origin(value_annotation)
    if origin in COLLECTION_ORIGINS:
        return (
            _collection_item_type_name(value_annotation),
            nullable,
            True,
            None,
        )
    nested_type = (
        value_annotation
        if isinstance(value_annotation, type) and is_dataclass(value_annotation)
        else None
    )
    return _type_name(value_annotation), nullable, False, nested_type


def _collection_item_type_name(annotation: object) -> str:
    arguments = tuple(
        argument for argument in get_args(annotation) if argument is not Ellipsis
    )
    if not arguments:
        return "object"
    names = tuple(dict.fromkeys(_type_name(argument) for argument in arguments))
    return " | ".join(names)


def _type_name(annotation: object) -> str:
    name = getattr(annotation, "__name__", None)
    if isinstance(name, str):
        return name
    return str(annotation).replace("typing.", "")
