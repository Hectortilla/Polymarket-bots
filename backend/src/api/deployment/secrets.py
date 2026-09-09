"""Runtime-only secret file ingress shared by database and Redis adapters."""

import os
from pathlib import Path


def configured_secret(name: str, default: str | None = None) -> str | None:
    file_name = f"{name}_FILE"
    path = os.environ.get(file_name)
    value = os.environ.get(name)
    if path is not None:
        if value is not None:
            raise ValueError(f"configure only one of {name} and {file_name}")
        try:
            value = Path(path).read_text().strip()
        except OSError:
            raise ValueError(f"cannot read {file_name}") from None
        if not value:
            raise ValueError(f"{file_name} must contain a nonempty value")
    return default if value is None else value
