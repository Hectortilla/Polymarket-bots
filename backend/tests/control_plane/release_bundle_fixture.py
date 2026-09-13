"""Explicit uncommitted source bundles for disposable operational rehearsals only."""

import json
import subprocess
from pathlib import Path

from api.deployment.release import RELEASE_ID_ENV

from scripts.deployment.bundle.archive import write_archive_contents
from scripts.deployment.bundle.contracts import (
    BUNDLE_METADATA_FILENAME,
    RELEASE_IMAGE_MANIFEST_FILENAME,
    REQUIRED_FILES,
)
from scripts.deployment.bundle.metadata import BundleMetadata
from scripts.deployment.paths import REPOSITORY, SOURCE_COMPOSE_PATH


def worktree_bundle(
    output: Path,
    images: dict[str, str],
    *,
    tag: str,
    compose_yaml: bytes | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> None:
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPOSITORY,
        )
        .decode()
        .split("\0")
    )
    contents = {
        name: (REPOSITORY / name).read_bytes()
        for name in names
        if name
        and (REPOSITORY / name).is_file()
        and (
            name.startswith(
                ("backend/src/", "backend/migrations/", "scripts/", "deploy/")
            )
            or name in REQUIRED_FILES
            or name == "backend/alembic.ini"
        )
    }
    contents[RELEASE_IMAGE_MANIFEST_FILENAME] = (
        "\n".join(f"{key}={value}" for key, value in images.items()) + "\n"
    ).encode()
    if compose_yaml is not None:
        contents[str(SOURCE_COMPOSE_PATH)] = compose_yaml
    contents.update(extra_files or {})
    metadata = BundleMetadata.for_contents(tag, images[RELEASE_ID_ENV], contents)
    metadata.verify_contents(contents)
    contents[BUNDLE_METADATA_FILENAME] = json.dumps(metadata.to_record()).encode()
    write_archive_contents(output, contents)
