"""Private filesystem inputs are validated before any backup or restore I/O."""

from pathlib import Path

PRIVATE_PERMISSION_MASK = 0o077


class PrivateBackupPath:
    @classmethod
    def directory(cls, path: Path) -> Path:
        resolved = cls._resolve(path)
        if not resolved.is_dir():
            raise ValueError("a private directory is required")
        return resolved

    @classmethod
    def file(cls, path: Path) -> Path:
        resolved = cls._resolve(path)
        if not resolved.is_file():
            raise ValueError("a private regular file is required")
        return resolved

    @staticmethod
    def _resolve(path: Path) -> Path:
        resolved = path.resolve(strict=True)
        if resolved.stat().st_mode & PRIVATE_PERMISSION_MASK:
            raise ValueError("backup paths must not grant group/other access")
        return resolved
