"""Literal dotenv serialization and regular-file parsing at release ingress."""

from collections.abc import Mapping
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values

from scripts.private_files import read_regular, write_private


def read_values(path: Path, *, required_mode: int | None = None) -> dict[str, str]:
    contents = read_regular(path, required_mode=required_mode).decode()
    return {
        key: value
        for key, value in dotenv_values(
            stream=StringIO(contents), interpolate=False
        ).items()
        if value is not None
    }


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
