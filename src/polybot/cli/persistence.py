"""Small dependency-light persistence primitives for CLI state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


class AtomicJsonFile:
    """Read and replace a JSON object atomically on the local filesystem."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(payload, dict):
            raise ValueError(f"state file must contain an object: {self.path}")
        return payload

    def write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, sort_keys=True, separators=(",", ":"))
            temporary.flush()
        try:
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)
