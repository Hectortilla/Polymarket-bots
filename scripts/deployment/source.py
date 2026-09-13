"""Read committed Compose files and build clean Git snapshots."""

import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from api.deployment.release import validate_release_id

from scripts.deployment.paths import REPOSITORY, SOURCE_COMPOSE_PATH


@dataclass(frozen=True)
class SourceSnapshot:
    commit: str
    directory: Path


def compose_for_release(source_commit: str, *, repository: Path = REPOSITORY) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{source_commit}:{SOURCE_COMPOSE_PATH.as_posix()}"],
        cwd=repository,
    )


@contextmanager
def clean_snapshot(repository: Path = REPOSITORY) -> Iterator[SourceSnapshot]:
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=repository
    )
    if status.strip():
        raise ValueError("commit repository changes before publishing a release")
    commit = validate_release_id(
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip()
    )
    with tempfile.TemporaryDirectory(prefix="polybot-build-") as temporary:
        work = Path(temporary)
        archive = work / "source.tar"
        subprocess.run(
            ["git", "archive", "--format=tar", "-o", str(archive), commit],
            cwd=repository,
            check=True,
        )
        context = work / "source"
        with tarfile.open(archive) as source:
            source.extractall(context, filter="data")
        yield SourceSnapshot(commit, context)
