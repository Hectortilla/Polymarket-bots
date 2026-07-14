"""Validation helpers for paginated official SDK responses."""

from __future__ import annotations


def page_items(page: object, *, context: str) -> tuple[object, ...]:
    """Return SDK page items after validating the response shape."""

    items = getattr(page, "items", None)
    if not isinstance(items, (list, tuple)):
        raise ValueError(f"{context} page items are malformed")
    return tuple(items)
