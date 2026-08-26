"""Shared graph-scalar annotation metadata."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from types import NoneType, UnionType
from typing import Union, get_args, get_origin

from polybot_control_plane.catalog.graphs.types import GraphScalarType


def without_none(annotation: object) -> tuple[object, bool]:
    if get_origin(annotation) not in {Union, UnionType}:
        return annotation, False
    arguments = get_args(annotation)
    non_none = tuple(argument for argument in arguments if argument is not NoneType)
    if len(non_none) == len(arguments):
        return annotation, False
    return (non_none[0] if len(non_none) == 1 else annotation), True


def scalar_type_for_annotation(annotation: object) -> GraphScalarType | None:
    annotation, _ = without_none(annotation)
    if annotation is bool:
        return GraphScalarType.BOOLEAN
    if annotation is int:
        return GraphScalarType.INTEGER
    if annotation is Decimal:
        return GraphScalarType.DECIMAL
    if annotation is str or (
        isinstance(annotation, type) and issubclass(annotation, Enum)
    ):
        return GraphScalarType.STRING
    return None
