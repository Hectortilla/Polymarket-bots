"""Typed image references, source identity, and release image roles."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from api.deployment.release import RELEASE_ID_ENV, validate_release_id

from scripts.deployment.dotenv import read_values


class ImageField(StrEnum):
    BACKEND = "POLYBOT_BACKEND_IMAGE"
    FRONTEND = "POLYBOT_FRONTEND_IMAGE"
    POSTGRES = "POLYBOT_POSTGRES_IMAGE"
    REDIS = "POLYBOT_REDIS_IMAGE"


class ImagePolicy(StrEnum):
    LOCAL_OR_REGISTRY = "local_or_registry"
    REGISTRY = "registry"


APPLICATION_IMAGES = {ImageField.BACKEND: "backend", ImageField.FRONTEND: "frontend"}
INFRASTRUCTURE_IMAGES = (ImageField.POSTGRES, ImageField.REDIS)
IMAGE_FIELDS = (*APPLICATION_IMAGES, *INFRASTRUCTURE_IMAGES)
SHA256_DIGEST_PATTERN = r"sha256:[a-f0-9]{64}"
# Docker Distribution name/tag grammar, with SHA-256 pinned separately below:
# https://github.com/distribution/reference/blob/main/regexp.go
IMAGE_PATH_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
REGISTRY_HOST_COMPONENT = r"(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])"
REGISTRY_HOST = (
    rf"(?:{REGISTRY_HOST_COMPONENT}(?:\.{REGISTRY_HOST_COMPONENT})*|\[[a-fA-F0-9:]+\])"
)
IMAGE_REPOSITORY_PATTERN = (
    rf"(?:{REGISTRY_HOST}(?::[0-9]+)?/)?"
    rf"{IMAGE_PATH_COMPONENT}(?:/{IMAGE_PATH_COMPONENT})*"
    r"(?::[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127})?"
)


@dataclass(frozen=True)
class ImageReference:
    repository: str | None
    digest: str

    @classmethod
    def parse(cls, value: str, *, policy: ImagePolicy) -> "ImageReference":
        repository, separator, digest = value.rpartition("@")
        if not separator:
            repository, digest = "", value
        if re.fullmatch(SHA256_DIGEST_PATTERN, digest) is None:
            raise ValueError("image must be pinned by SHA-256 digest")
        if repository:
            cls.validate_repository(repository)
        if (separator or policy is ImagePolicy.REGISTRY) and not repository:
            raise ValueError("image must have a pullable registry reference")
        return cls(repository or None, digest)

    @staticmethod
    def validate_repository(repository: str) -> None:
        if re.fullmatch(IMAGE_REPOSITORY_PATTERN, repository) is None:
            raise ValueError("invalid image repository")

    def __str__(self) -> str:
        return f"{self.repository}@{self.digest}" if self.repository else self.digest


@dataclass(frozen=True)
class ReleaseImages:
    source_commit: str
    references: Mapping[ImageField, ImageReference]

    @classmethod
    def read(
        cls, path: Path, *, policy: ImagePolicy = ImagePolicy.REGISTRY
    ) -> "ReleaseImages":
        return cls.from_values(read_values(path), policy=policy)

    @classmethod
    def from_values(
        cls, values: Mapping[str, str], *, policy: ImagePolicy
    ) -> "ReleaseImages":
        source_commit = validate_release_id(values.get(RELEASE_ID_ENV, ""))
        references = {}
        for field in IMAGE_FIELDS:
            try:
                references[field] = ImageReference.parse(
                    values.get(field, ""), policy=policy
                )
            except ValueError as error:
                raise ValueError(f"{field}: {error}") from None
        return cls(source_commit, MappingProxyType(references))

    def to_values(self) -> dict[str, str]:
        return {
            RELEASE_ID_ENV: self.source_commit,
            **{field.value: str(self.references[field]) for field in IMAGE_FIELDS},
        }

    def require_same_infrastructure(self, candidate: "ReleaseImages") -> None:
        if any(
            self.references[field] != candidate.references[field]
            for field in INFRASTRUCTURE_IMAGES
        ):
            raise ValueError(
                "infrastructure image changes require a separate maintenance plan"
            )
