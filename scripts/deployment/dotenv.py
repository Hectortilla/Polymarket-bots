"""Literal dotenv serialization and regular-file parsing at release ingress."""

from collections.abc import Mapping
from io import StringIO
from pathlib import Path

from dotenv.parser import parse_stream

from scripts.private_files import read_regular, write_private


def read_values(path: Path, *, required_mode: int | None = None) -> dict[str, str]:
    contents = read_regular(path, required_mode=required_mode).decode()
    return parse_values(contents)


def parse_values(contents: str) -> dict[str, str]:
    values = {}
    seen = set()
    for binding in parse_stream(StringIO(contents)):
        if binding.error or (binding.key is not None and binding.key in seen):
            raise ValueError("invalid or duplicate manifest assignment")
        if binding.key is not None:
            seen.add(binding.key)
            if binding.value is not None:
                values[binding.key] = binding.value
    return values


def write_manifest(
    path: Path, values: Mapping[str, str], *, replace: bool = True
) -> None:
    lines = [f"{name}={quote_value(value)}\n" for name, value in values.items()]
    write_private(path, "".join(lines).encode(), replace=replace)


def quote_value(value: str) -> str:
    if any(character in value for character in "\r\n\0"):
        raise ValueError("manifest values must be single-line text")
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"
