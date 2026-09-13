"""Verified release artifacts with one metadata and image-provenance contract."""

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.deployment.bundle.archive import (
    read_archive_contents,
    write_archive_contents,
)
from scripts.deployment.bundle.contracts import (
    BUNDLE_METADATA_FILENAME,
    RELEASE_IMAGE_MANIFEST_FILENAME,
)
from scripts.deployment.bundle.installed import read_installed_contents
from scripts.deployment.bundle.metadata import BundleMetadata
from scripts.deployment.bundle.source import read_committed_contents
from scripts.deployment.images import ReleaseImages
from scripts.private_files import read_regular


@dataclass(frozen=True)
class ReleaseBundle:
    metadata: BundleMetadata
    images: ReleaseImages

    @classmethod
    def create(
        cls, source: Path, images_manifest_path: Path, tag: str, output: Path
    ) -> "ReleaseBundle":
        images, contents = read_committed_contents(source, images_manifest_path)
        contents[RELEASE_IMAGE_MANIFEST_FILENAME] = read_regular(images_manifest_path)
        metadata = BundleMetadata.for_contents(tag, images.source_commit, contents)
        verified_images = metadata.verify_contents(contents)
        contents[BUNDLE_METADATA_FILENAME] = json.dumps(
            metadata.to_record(), sort_keys=True
        ).encode()
        write_archive_contents(output, contents)
        return cls(metadata, verified_images)

    @classmethod
    def from_archive(
        cls,
        bundle_archive_path: Path,
        *,
        commit: str | None = None,
        tag: str | None = None,
    ) -> "ReleaseBundle":
        contents = read_archive_contents(bundle_archive_path)
        try:
            record = json.loads(contents.pop(BUNDLE_METADATA_FILENAME))
        except KeyError:
            raise ValueError("incomplete release bundle") from None
        metadata = BundleMetadata.from_record(record)
        metadata.require_provenance(commit=commit, tag=tag)
        return cls(metadata, metadata.verify_contents(contents))

    @classmethod
    def from_directory(cls, directory: Path) -> "ReleaseBundle":
        metadata = BundleMetadata.from_record(
            json.loads(read_regular(directory / BUNDLE_METADATA_FILENAME))
        )
        contents = read_installed_contents(directory, metadata)
        return cls(metadata, metadata.verify_contents(contents))
