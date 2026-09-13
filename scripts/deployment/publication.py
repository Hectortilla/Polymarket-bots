"""Reuse only a complete GitHub release with verified bundle provenance."""

import argparse
from enum import StrEnum
from pathlib import Path

from scripts.deployment.bundle import ReleaseBundle
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.deployment.github import GitHubRelease
from scripts.deployment.identity import validate_release_tag


class PublicationOutput(StrEnum):
    REUSE = "reuse"


def reuse_published_bundle(tag: str, commit: str, directory: Path) -> bool:
    validate_release_tag(tag)
    # Listing distinguishes absence from authentication or network failure.
    release = GitHubRelease.find(tag)
    if release is None:
        return False
    if release.draft or release.asset_names != (RELEASE_BUNDLE_FILENAME,):
        raise ValueError(
            "partial/conflicting release publication; inspect the draft/assets before retrying"
        )
    directory.mkdir(parents=True, exist_ok=True)
    release.download_bundle(directory)
    ReleaseBundle.from_archive(
        directory / RELEASE_BUNDLE_FILENAME, commit=commit, tag=tag
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("commit")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    reused = reuse_published_bundle(args.tag, args.commit, args.directory)
    print(f"{PublicationOutput.REUSE}={str(reused).lower()}")


if __name__ == "__main__":
    main()
