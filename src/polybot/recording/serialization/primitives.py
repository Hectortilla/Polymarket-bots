"""Canonical JSON primitives for recording serialization."""

from __future__ import annotations

import json

from .parsing import load_json_value, require_text


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("recording payload is not JSON serializable") from error


def text_tuple_json(values: tuple[str, ...]) -> str:
    return canonical_json(list(values))


def text_tuple_from_json(raw_json: str, name: str) -> tuple[str, ...]:
    value = load_json_value(raw_json)
    if not isinstance(value, list):
        raise ValueError(f"recording {name} must be a JSON array")
    return tuple(require_text(item, name) for item in value)
