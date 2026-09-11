"""Bounded pg_dump/age process lifetime and private encrypted staging files."""

import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from scripts.beta_backup.database import ComposeDatabase
from scripts.beta_backup.policy import AGE_BINARY, BACKUP_PROCESS_TIMEOUT_SECONDS


class EncryptedDump:
    def __init__(
        self, database: ComposeDatabase, directory: Path, recipients: Path
    ) -> None:
        self._database = database
        self._directory = directory
        self._recipients = recipients.resolve(strict=True)
        if not self._recipients.is_file():
            raise ValueError("an age recipients file is required")

    @contextmanager
    def stage(self):
        temporary_archive_path = None
        dump_process = None
        encryption_process = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self._directory, prefix=".incomplete-", delete=False
            ) as output:
                temporary_archive_path = Path(output.name)
                dump_process = subprocess.Popen(
                    self._database.dump_command(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=self._database.project.environment,
                )
                encryption_process = subprocess.Popen(
                    [
                        AGE_BINARY,
                        "--encrypt",
                        "--recipients-file",
                        str(self._recipients),
                    ],
                    stdin=dump_process.stdout,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                )
                dump_process.stdout.close()
                self._require_pipeline_success(dump_process, encryption_process)
                output.flush()
                os.fsync(output.fileno())
            yield temporary_archive_path
        finally:
            for process in (encryption_process, dump_process):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait()
            if temporary_archive_path is not None:
                temporary_archive_path.unlink(missing_ok=True)

    @staticmethod
    def _require_pipeline_success(
        dump_process: subprocess.Popen, encryption_process: subprocess.Popen
    ) -> None:
        encryption_status = encryption_process.wait(
            timeout=BACKUP_PROCESS_TIMEOUT_SECONDS
        )
        dump_status = dump_process.wait(timeout=BACKUP_PROCESS_TIMEOUT_SECONDS)
        if encryption_status != 0 or dump_status != 0:
            raise RuntimeError(
                "backup pipeline failed; no successful archive published"
            )
