"""GitHub CLI release reuse with immutable, complete bundle provenance."""

import argparse
import json
import subprocess
from pathlib import Path

from scripts.deployment.bundle import BUNDLE_NAME, validate_tag, verify


def published(tag: str, commit: str, directory: Path) -> bool:
    validate_tag(tag)
    # Listing distinguishes a missing release from authentication/network failure.
    releases = json.loads(
        subprocess.check_output(
            ["gh", "api", "--paginate", "--slurp", "repos/{owner}/{repo}/releases"],
            text=True,
        )
    )
    release = next(
        (item for page in releases for item in page if item["tag_name"] == tag), None
    )
    if release is None:
        return False
    if {asset["name"] for asset in release["assets"]} != {BUNDLE_NAME} or release[
        "draft"
    ]:
        raise ValueError(
            "partial/conflicting release publication; inspect the draft/assets before retrying"
        )
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gh",
            "release",
            "download",
            tag,
            "--pattern",
            BUNDLE_NAME,
            "--dir",
            str(directory),
        ],
        check=True,
    )
    verify(directory / BUNDLE_NAME, commit=commit, tag=tag)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("commit")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(
        "reuse=true"
        if published(args.tag, args.commit, args.directory)
        else "reuse=false"
    )


if __name__ == "__main__":
    main()
