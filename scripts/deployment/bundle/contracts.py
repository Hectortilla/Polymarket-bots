"""Release artifact names, required source members and CLI vocabulary."""

from enum import StrEnum
from pathlib import PurePosixPath

from scripts.deployment.paths import SOURCE_COMPOSE_PATH


class BundleOperation(StrEnum):
    CREATE = "create"
    VERIFY = "verify"


RELEASE_BUNDLE_FILENAME = "release.tar.gz"
BUNDLE_METADATA_FILENAME = "bundle.json"
RELEASE_IMAGE_MANIFEST_FILENAME = "images.env"
REQUIRED_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "README.md",
        str(SOURCE_COMPOSE_PATH),
        RELEASE_IMAGE_MANIFEST_FILENAME,
    }
)


def validate_member_name(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("unsafe bundle member")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise ValueError("unsafe bundle member")
    return value
