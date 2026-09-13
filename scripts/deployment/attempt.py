"""Persisted deployment-attempt identity and phase validation."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from scripts.deployment.paths import HOST_COMPOSE_NAME, MANIFEST_NAME

HISTORY_DIRECTORY_NAME = "releases"
JOURNAL_NAME = ".deployment.json"
LOCK_NAME = ".deploy.lock"
PREVIOUS_MANIFEST_NAME = "previous.env"
PREVIOUS_COMPOSE_NAME = "previous-compose.yml"
INVALID_JOURNAL_MESSAGE = "invalid deployment journal; inspect it before retrying"


class JournalField(StrEnum):
    DIRECTORY = "directory"
    PHASE = "phase"
    ROLLBACK = "rollback"


class AttemptPhase(StrEnum):
    ACTIVATING = "activating"
    ACTIVATED = "activated"


@dataclass(frozen=True)
class DeploymentAttempt:
    directory: Path
    phase: AttemptPhase
    rollback: bool

    @property
    def manifest(self) -> Path:
        return self.directory / MANIFEST_NAME

    @property
    def compose_file(self) -> Path:
        return self.directory / HOST_COMPOSE_NAME

    @classmethod
    def from_record(cls, history: Path, record: object) -> "DeploymentAttempt":
        try:
            if (
                not isinstance(record, dict)
                or type(record[JournalField.ROLLBACK]) is not bool
            ):
                raise ValueError
            name = record[JournalField.DIRECTORY]
            if (
                not isinstance(name, str)
                or not name
                or Path(name).name != name
                or name in {".", ".."}
            ):
                raise ValueError
            directory = history / name
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError
            return cls(
                directory,
                AttemptPhase(record[JournalField.PHASE]),
                record[JournalField.ROLLBACK],
            )
        except (KeyError, ValueError, TypeError):
            raise ValueError(INVALID_JOURNAL_MESSAGE) from None

    def to_record(self) -> dict[str, str | bool]:
        return {
            JournalField.DIRECTORY: self.directory.name,
            JournalField.PHASE: self.phase.value,
            JournalField.ROLLBACK: self.rollback,
        }
