"""Buildx CLI calls and metadata normalization for registry image references."""

import json
import subprocess
import tempfile
from enum import StrEnum
from pathlib import Path

from scripts.deployment.images import ImagePolicy, ImageReference
from scripts.deployment.paths import SOURCE_DEPLOY_DIRECTORY
from scripts.deployment.source import SourceSnapshot


class BuildPlatform(StrEnum):
    AMD64 = "linux/amd64"
    ARM64 = "linux/arm64"


def build_image(
    source: SourceSnapshot, component: str, repository: str, platform: BuildPlatform
) -> ImageReference:
    with tempfile.TemporaryDirectory(prefix="polybot-build-metadata-") as temporary:
        metadata = Path(temporary) / "result.json"
        subprocess.run(
            [
                "docker",
                "buildx",
                "build",
                "--platform",
                platform.value,
                "--push",
                "--file",
                str(
                    source.directory
                    / SOURCE_DEPLOY_DIRECTORY
                    / f"{component}.Dockerfile"
                ),
                "--tag",
                f"{repository}:{source.commit}",
                "--label",
                f"org.opencontainers.image.revision={source.commit}",
                "--metadata-file",
                str(metadata),
                str(source.directory),
            ],
            check=True,
        )
        return reference_from_metadata(
            repository, metadata.read_text(), "containerimage.digest"
        )


def resolve_image(image: str) -> ImageReference:
    if "@" in image:
        ImageReference.parse(image, policy=ImagePolicy.REGISTRY)
    else:
        ImageReference.validate_repository(image)
    metadata = subprocess.check_output(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            image,
            "--format",
            "{{json .Manifest}}",
        ],
        text=True,
    )
    return reference_from_metadata(image.split("@")[0], metadata, "digest")


def reference_from_metadata(repository: str, metadata: str, key: str) -> ImageReference:
    try:
        digest = json.loads(metadata)[key]
        if not isinstance(digest, str):
            raise TypeError("digest is not text")
        return ImageReference.parse(
            f"{repository}@{digest}", policy=ImagePolicy.REGISTRY
        )
    except (ValueError, KeyError, TypeError):
        raise ValueError("Buildx did not return valid SHA-256 image metadata") from None
