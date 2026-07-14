"""Stable compact labels for token identifiers in the dashboard."""

from __future__ import annotations


def format_token_label(token_id: str) -> str:
    return token_id if len(token_id) <= 12 else f"{token_id[:7]}…{token_id[-4:]}"
