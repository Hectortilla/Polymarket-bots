"""Regular-file ingress and durable atomic writes with private host permissions."""

import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700


def read_regular(path: Path, *, required_mode: int | None = None) -> bytes:
    with regular_file(path, required_mode=required_mode) as source:
        return source.read()


@contextmanager
def regular_file(
    path: Path, *, create: bool = False, required_mode: int | None = None
) -> Iterator[BinaryIO]:
    access = os.O_RDWR | os.O_CREAT if create else os.O_RDONLY
    descriptor = os.open(
        path, access | os.O_NONBLOCK | os.O_NOFOLLOW, PRIVATE_FILE_MODE
    )
    with os.fdopen(descriptor, "r+b" if create else "rb", buffering=0) as source:
        status = os.fstat(source.fileno())
        if not stat.S_ISREG(status.st_mode):
            raise ValueError(f"{path.name} must be a regular file")
        if required_mode is not None and stat.S_IMODE(status.st_mode) != required_mode:
            raise ValueError(f"{path.name} must have mode {required_mode:o}")
        yield source


def write_private(
    path: Path, content: bytes, *, mode: int = PRIVATE_FILE_MODE, replace: bool = True
) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing to replace symlink: {path.name}")
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".deploy-")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            os.fchmod(output.fileno(), mode)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # A hard link publishes the complete file without clobbering a
            # manifest created by a concurrent publisher during the build.
            os.link(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
