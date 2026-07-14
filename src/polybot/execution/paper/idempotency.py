"""Durable source-claim storage for paper execution."""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import Protocol


DUPLICATE_SOURCE_MESSAGE = "source event was already processed"


class SourceIdempotencyStore(Protocol):
    def claim(self, source_id: str) -> bool:
        ...

    def release(self, source_id: str) -> None:
        ...


class FileSourceIdempotencyStore:
    """Persist source claims in an atomically locked append-only text file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def claim(self, source_id: str) -> bool:
        return self._claim_sync(source_id)

    def release(self, source_id: str) -> None:
        self._release_sync(source_id)

    def _claim_sync(self, source_id: str) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                claimed = {line.rstrip("\n") for line in handle}
                if source_id in claimed:
                    return False
                handle.seek(0, 2)
                handle.write(source_id + "\n")
                handle.flush()
                return True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _release_sync(self, source_id: str) -> None:
        if not self._path.exists():
            return
        with self._path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                remaining = [line for line in handle if line.rstrip("\n") != source_id]
                handle.seek(0)
                handle.truncate()
                handle.writelines(remaining)
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
