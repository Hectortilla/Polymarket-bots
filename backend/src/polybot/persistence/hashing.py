"""Streaming SHA-256 fingerprints for persisted files."""

import hashlib
from pathlib import Path

SHA256_ALGORITHM = "sha256"


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, SHA256_ALGORITHM).hexdigest()
