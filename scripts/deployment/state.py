"""Durable host deployment attempts, locking, and recoverable file promotion."""

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from scripts.deployment.attempt import (
    HISTORY_DIRECTORY_NAME,
    INVALID_JOURNAL_MESSAGE,
    JOURNAL_NAME,
    LOCK_NAME,
    PREVIOUS_COMPOSE_NAME,
    PREVIOUS_MANIFEST_NAME,
    AttemptPhase,
    DeploymentAttempt,
)
from scripts.deployment.candidate import PromotionCandidate
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import (
    CURRENT_RELEASE_NAME,
    HOST_COMPOSE_NAME,
    MANIFEST_NAME,
    NEXT_RELEASE_NAME,
)
from scripts.private_files import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    read_regular,
    regular_file,
    sync_directory,
    write_private,
)


class DeploymentState:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.manifest = self.directory / MANIFEST_NAME
        self.compose_file = self.directory / HOST_COMPOSE_NAME
        self.history = self.directory / HISTORY_DIRECTORY_NAME
        self.journal = self.directory / JOURNAL_NAME

    @contextmanager
    def locked(self) -> Iterator[None]:
        with regular_file(self.directory / LOCK_NAME, create=True) as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError(
                    "another deployment is already running for this app"
                ) from None
            yield

    def pending(self) -> DeploymentAttempt | None:
        if not self.journal.exists() and not self.journal.is_symlink():
            return None
        self._require_history_directory()
        try:
            record = json.loads(
                read_regular(self.journal, required_mode=PRIVATE_FILE_MODE)
            )
        except (ValueError, OSError):
            raise ValueError(INVALID_JOURNAL_MESSAGE) from None
        return DeploymentAttempt.from_record(self.history, record)

    def prepare(
        self, settings: RuntimeManifest, compose_yaml: bytes, *, rollback: bool
    ) -> DeploymentAttempt:
        self.history.mkdir(mode=PRIVATE_DIRECTORY_MODE, exist_ok=True)
        self._require_history_directory()
        directory = Path(
            tempfile.mkdtemp(
                prefix=f"{settings.images.source_commit[:12]}-", dir=self.history
            )
        )
        attempt = DeploymentAttempt(directory, AttemptPhase.ACTIVATING, rollback)
        if self.manifest.exists():
            write_private(
                directory / PREVIOUS_MANIFEST_NAME,
                read_regular(self.manifest, required_mode=PRIVATE_FILE_MODE),
            )
            write_private(
                directory / PREVIOUS_COMPOSE_NAME, read_regular(self.compose_file)
            )
        write_manifest(attempt.manifest, settings.to_values())
        write_private(attempt.compose_file, compose_yaml)
        sync_directory(self.history)
        return attempt

    def begin_activation(self, attempt: DeploymentAttempt) -> None:
        if attempt.phase is not AttemptPhase.ACTIVATING:
            raise ValueError("only a pending activation can be started")
        self._record(attempt)

    def mark_activated(self, attempt: DeploymentAttempt) -> DeploymentAttempt:
        if attempt.phase is not AttemptPhase.ACTIVATING:
            raise ValueError("only a pending activation can be marked successful")
        activated = replace(attempt, phase=AttemptPhase.ACTIVATED)
        self._record(activated)
        return activated

    def promote(self, attempt: DeploymentAttempt) -> None:
        if attempt.phase is not AttemptPhase.ACTIVATED:
            raise ValueError("only a successful activation can be promoted")
        candidate = PromotionCandidate.read(attempt, self.directory)
        # Keep the journal until all three active pointers are durable. A retry
        # finishes this verified candidate even after a partial replacement.
        write_private(self.compose_file, candidate.compose_yaml)
        write_private(self.manifest, candidate.manifest_values)
        next_release_link = self.directory / NEXT_RELEASE_NAME
        next_release_link.unlink(missing_ok=True)
        next_release_link.symlink_to(
            candidate.bundle_directory, target_is_directory=True
        )
        os.replace(next_release_link, self.directory / CURRENT_RELEASE_NAME)
        sync_directory(self.directory)
        self.journal.unlink()
        sync_directory(self.directory)

    def _record(self, attempt: DeploymentAttempt) -> None:
        write_private(self.journal, json.dumps(attempt.to_record()).encode())

    def _require_history_directory(self) -> None:
        if self.history.is_symlink() or not self.history.is_dir():
            raise ValueError("deployment history must be a real directory")
