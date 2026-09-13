"""Release operation and version-tag contracts shared by deployment callers."""

import re
from enum import StrEnum


class DeploymentOperation(StrEnum):
    DEPLOY = "deploy"
    ROLLBACK = "rollback"


RELEASE_TAG_PATTERN = r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"


def validate_release_tag(tag: str) -> str:
    if not isinstance(tag, str) or re.fullmatch(RELEASE_TAG_PATTERN, tag) is None:
        raise ValueError("release tag must be vMAJOR.MINOR.PATCH")
    return tag
