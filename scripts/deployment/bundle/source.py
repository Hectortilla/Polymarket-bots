"""Committed operational source selection at the CI checkout boundary."""

import subprocess
from pathlib import Path

from scripts.deployment.bundle.contracts import REQUIRED_FILES
from scripts.deployment.images import ReleaseImages
from scripts.private_files import read_regular


def read_committed_contents(
    source: Path, images_manifest_path: Path
) -> tuple[ReleaseImages, dict[str, bytes]]:
    images = ReleaseImages.read(images_manifest_path)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if commit != images.source_commit:
        raise ValueError("checkout does not match image provenance")
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=source)
        .decode()
        .split("\0")
    )
    names = _release_source_files(tracked)
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", *names],
        cwd=source,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    if any((source / name).is_symlink() for name in names):
        raise ValueError("release source must contain regular files")
    return images, {name: read_regular(source / name) for name in names}


def _release_source_files(tracked_paths: list[str]) -> list[str]:
    return [
        name
        for name in tracked_paths
        if name
        and (
            name.startswith(
                ("backend/src/", "backend/migrations/", "scripts/", "deploy/")
            )
            or name in REQUIRED_FILES
            or name == "backend/alembic.ini"
        )
    ]
