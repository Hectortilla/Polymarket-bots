"""Dataclass field discovery for graph trigger payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from pydantic import TypeAdapter


COLLECTION_ORIGINS = frozenset({list, tuple})


@dataclass(frozen=True, slots=True)
class DiscoveredGraphField:
    path: tuple[str, ...]
    value_type: str
    nullable: bool
    collection: bool
    value_schema: Mapping[str, object]


def discover_graph_fields(payload_type: type[Any]) -> tuple[DiscoveredGraphField, ...]:
    if not is_dataclass(payload_type):
        raise TypeError("graph trigger payloads must be dataclass types")
    return _discover_dataclass_fields(payload_type, path_prefix=())


def _discover_dataclass_fields(
    payload_type: type[Any],
    *,
    path_prefix: tuple[str, ...],
) -> tuple[DiscoveredGraphField, ...]:
    type_hints = get_type_hints(payload_type)
    discovered: list[DiscoveredGraphField] = []
    for field in fields(payload_type):
        annotation = type_hints[field.name]
        path = (*path_prefix, field.name)
        value_type, nullable, collection, nested_type = _describe_annotation(annotation)
        discovered.append(
            DiscoveredGraphField(
                path=path,
                value_type=value_type,
                nullable=nullable,
                collection=collection,
                value_schema=TypeAdapter(annotation).json_schema(),
            )
        )
        if nested_type is not None and not collection:
            discovered.extend(
                _discover_dataclass_fields(nested_type, path_prefix=path)
            )
    return tuple(discovered)


def _describe_annotation(
    annotation: object,
) -> tuple[str, bool, bool, type[Any] | None]:
    value_annotation, nullable = _without_none(annotation)
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


def _without_none(annotation: object) -> tuple[object, bool]:
    origin = get_origin(annotation)
    if origin not in {Union, UnionType}:
        return annotation, False
    arguments = get_args(annotation)
    non_none = tuple(argument for argument in arguments if argument is not NoneType)
    if len(non_none) == len(arguments):
        return annotation, False
    if len(non_none) != 1:
        return annotation, True
    return non_none[0], True


def _collection_item_type_name(annotation: object) -> str:
    arguments = tuple(argument for argument in get_args(annotation) if argument is not Ellipsis)
    if not arguments:
        return "object"
    names = tuple(dict.fromkeys(_type_name(argument) for argument in arguments))
    return " | ".join(names)


def _type_name(annotation: object) -> str:
    name = getattr(annotation, "__name__", None)
    if isinstance(name, str):
        return name
    return str(annotation).replace("typing.", "")
