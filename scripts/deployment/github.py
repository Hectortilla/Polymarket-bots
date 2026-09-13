"""GitHub CLI release payloads normalized before publication decisions."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.deployment.errors import DeploymentInputError

RELEASE_WORKFLOW_ARTIFACT_NAME = "release-bundle"


@dataclass(frozen=True)
class GitHubRelease:
    tag: str
    draft: bool
    asset_names: tuple[str, ...]

    @classmethod
    def find(cls, tag: str) -> "GitHubRelease | None":
        pages = json.loads(
            subprocess.check_output(
                ["gh", "api", "--paginate", "--slurp", "repos/{owner}/{repo}/releases"],
                text=True,
            )
        )
        releases = cls.parse_pages(pages)
        return _find_release_by_tag(releases, tag)

    @classmethod
    def parse_pages(cls, pages: object) -> tuple["GitHubRelease", ...]:
        if not isinstance(pages, list) or any(
            not isinstance(page, list) for page in pages
        ):
            raise DeploymentInputError("invalid GitHub release pages")
        releases = []
        tags = set()
        for page in pages:
            for row in page:
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("tag_name"), str)
                    or type(row.get("draft")) is not bool
                    or not isinstance(row.get("assets"), list)
                ):
                    raise DeploymentInputError("invalid GitHub release record")
                names = []
                for asset in row["assets"]:
                    if not isinstance(asset, dict) or not isinstance(
                        asset.get("name"), str
                    ):
                        raise DeploymentInputError("invalid GitHub release asset")
                    names.append(asset["name"])
                if row["tag_name"] in tags or len(names) != len(set(names)):
                    raise DeploymentInputError("ambiguous GitHub release record")
                tags.add(row["tag_name"])
                releases.append(cls(row["tag_name"], row["draft"], tuple(names)))
        return tuple(releases)

    def download_bundle(self, directory: Path) -> None:
        subprocess.run(
            [
                "gh",
                "release",
                "download",
                self.tag,
                "--pattern",
                RELEASE_BUNDLE_FILENAME,
                "--dir",
                str(directory),
            ],
            check=True,
        )


def _find_release_by_tag(
    releases: tuple[GitHubRelease, ...], tag: str
) -> GitHubRelease | None:
    for release in releases:
        if release.tag == tag:
            return release
    return None
