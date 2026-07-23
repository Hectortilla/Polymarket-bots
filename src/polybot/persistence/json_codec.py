"""Strict JSON decoding for durable and configuration inputs."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


class DuplicateJsonKeyError(ValueError):
    pass


class NonFiniteJsonNumberError(ValueError):
    pass


def loads_json(raw: str) -> object:
    """Decode JSON while rejecting duplicate keys and non-finite numbers."""
    return json.loads(
        raw,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_nonfinite_number,
    )


def _unique_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise NonFiniteJsonNumberError(f"JSON number must be finite: {value}")
