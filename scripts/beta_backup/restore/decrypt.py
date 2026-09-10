"""Authenticate a complete age stream before yielding private temporary plaintext."""

import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from scripts.beta_backup.paths import PrivateBackupPath
from scripts.beta_backup.policy import AGE_BINARY, BACKUP_PROCESS_TIMEOUT_SECONDS


class DecryptedArchive:
    def __init__(self, archive: Path, identity: Path, scratch_directory: Path) -> None:
        self.archive = archive.resolve(strict=True)
        self.identity = PrivateBackupPath.file(identity)
        self.scratch_directory = PrivateBackupPath.directory(scratch_directory)
        if not self.archive.is_file():
            raise ValueError("a regular encrypted archive is required")

    @contextmanager
    def open(self):
        with tempfile.TemporaryFile(dir=self.scratch_directory) as plaintext:
            subprocess.run(
                [
                    AGE_BINARY,
                    "--decrypt",
                    "--identity",
                    str(self.identity),
                    str(self.archive),
                ],
                stdout=plaintext,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=BACKUP_PROCESS_TIMEOUT_SECONDS,
            )
            plaintext.seek(0)
            yield plaintext
