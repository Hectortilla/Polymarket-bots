"""Validated persistent bundle metadata and shared content-integrity rules."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from api.deployment.release import validate_release_id
from polybot.persistence.hashing import SHA256_ALGORITHM

from scripts.deployment.bundle.contracts import (
    BUNDLE_METADATA_FILENAME,
    RELEASE_IMAGE_MANIFEST_FILENAME,
    REQUIRED_FILES,
    validate_member_name,
)
from scripts.deployment.dotenv import parse_values
from scripts.deployment.errors import DeploymentInputError
from scripts.deployment.identity import validate_release_tag
from scripts.deployment.images import ImagePolicy, ReleaseImages


@dataclass(frozen=True)
class BundleMetadata:
    tag: str
    commit: str
    files: Mapping[str, str]

    @classmethod
    def from_record(cls, record: object) -> "BundleMetadata":
        if not isinstance(record, dict) or set(record) != {"tag", "commit", "files"}:
            raise DeploymentInputError("invalid bundle metadata")
        tag = validate_release_tag(record["tag"])
        if not isinstance(record["commit"], str):
            raise DeploymentInputError("invalid bundle commit")
        commit = validate_release_id(record["commit"])
        files = record["files"]
        if not isinstance(files, dict) or not REQUIRED_FILES <= files.keys():
            raise DeploymentInputError("incomplete release bundle")
        for name, digest in files.items():
            validate_member_name(name)
            if (
                name == BUNDLE_METADATA_FILENAME
                or not isinstance(digest, str)
                or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            ):
                raise DeploymentInputError("invalid bundle file digest")
        return cls(tag, commit, MappingProxyType(dict(files)))

    @classmethod
    def for_contents(
        cls, tag: str, commit: str, contents: Mapping[str, bytes]
    ) -> "BundleMetadata":
        return cls.from_record(
            {
                "tag": tag,
                "commit": commit,
                "files": {
                    name: hashlib.new(SHA256_ALGORITHM, data).hexdigest()
                    for name, data in contents.items()
                },
            }
        )

    def to_record(self) -> dict[str, object]:
        return {"tag": self.tag, "commit": self.commit, "files": dict(self.files)}

    def require_provenance(
        self, *, commit: str | None = None, tag: str | None = None
    ) -> None:
        if (commit is not None and self.commit != commit) or (
            tag is not None and self.tag != tag
        ):
            raise DeploymentInputError("release provenance mismatch")

    def verify_contents(self, contents: Mapping[str, bytes]) -> ReleaseImages:
        if set(contents) != set(self.files):
            raise DeploymentInputError("incomplete release bundle")
        for name, digest in self.files.items():
            if hashlib.new(SHA256_ALGORITHM, contents[name]).hexdigest() != digest:
                raise DeploymentInputError("release content checksum mismatch")
        images = ReleaseImages.from_values(
            parse_values(contents[RELEASE_IMAGE_MANIFEST_FILENAME].decode()),
            policy=ImagePolicy.REGISTRY,
        )
        if images.source_commit != self.commit:
            raise DeploymentInputError("image provenance mismatch")
        return images
