"""Content-verified, non-secret release bundles built from a CI checkout."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

from dotenv import dotenv_values

from scripts.deployment.images import ImagePolicy, ReleaseImages

BUNDLE_NAME = "release.tar.gz"
METADATA_NAME = "bundle.json"
IMAGES_NAME = "images.env"
TAG_PATTERN = r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
REQUIRED_FILES = {
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "deploy/compose.yaml",
    IMAGES_NAME,
}


def validate_tag(tag: str) -> str:
    if re.fullmatch(TAG_PATTERN, tag) is None:
        raise ValueError("release tag must be vMAJOR.MINOR.PATCH")
    return tag


def create(source: Path, images: Path, tag: str, output: Path) -> None:
    validate_tag(tag)
    release = ReleaseImages.read(images)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if commit != release.source_commit:
        raise ValueError("checkout does not match image provenance")
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=source)
        .decode()
        .split("\0")
    )
    names = [
        name
        for name in tracked
        if name
        and (
            name.startswith(
                ("backend/src/", "backend/migrations/", "scripts/", "deploy/")
            )
            or name in REQUIRED_FILES
            or name == "backend/alembic.ini"
        )
    ]
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", *names],
        cwd=source,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    if any((source / name).is_symlink() for name in names):
        raise ValueError("release source must contain regular files")
    contents = {name: (source / name).read_bytes() for name in names}
    contents[IMAGES_NAME] = images.read_bytes()
    metadata = {
        "tag": tag,
        "commit": commit,
        "files": {
            name: hashlib.sha256(data).hexdigest() for name, data in contents.items()
        },
    }
    contents[METADATA_NAME] = json.dumps(metadata, sort_keys=True).encode()
    with (
        output.open("xb") as destination,
        tarfile.open(fileobj=destination, mode="w:gz") as archive,
    ):
        for name, content in sorted(contents.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(content), 0o644
            archive.addfile(info, io.BytesIO(content))


def verify(path: Path, *, commit: str | None = None, tag: str | None = None) -> dict:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError("duplicate bundle member")
        for member in members:
            name = PurePosixPath(member.name)
            if (
                not member.isfile()
                or name.is_absolute()
                or ".." in name.parts
                or str(name) != member.name
            ):
                raise ValueError("unsafe bundle member")
        metadata = json.load(archive.extractfile(METADATA_NAME))
        validate_tag(metadata["tag"])
        if (commit and metadata["commit"] != commit) or (
            tag and metadata["tag"] != tag
        ):
            raise ValueError("release provenance mismatch")
        if set(names) != set(metadata["files"]) | {
            METADATA_NAME
        } or not REQUIRED_FILES <= set(names):
            raise ValueError("incomplete release bundle")
        for name, digest in metadata["files"].items():
            if hashlib.sha256(archive.extractfile(name).read()).hexdigest() != digest:
                raise ValueError("release content checksum mismatch")
        # Validate image data without extracting untrusted paths.
        values = dotenv_values(
            stream=io.StringIO(archive.extractfile(IMAGES_NAME).read().decode()),
            interpolate=False,
        )
        images = ReleaseImages.from_values(values, policy=ImagePolicy.REGISTRY)
        if images.source_commit != metadata["commit"]:
            raise ValueError("image provenance mismatch")
        return metadata


def verify_directory(directory: Path) -> ReleaseImages:
    metadata = json.loads((directory / METADATA_NAME).read_text())
    validate_tag(metadata["tag"])
    if not REQUIRED_FILES <= set(metadata["files"]):
        raise ValueError("incomplete installed bundle")
    for name, digest in metadata["files"].items():
        path = directory / name
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(directory.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("installed release content mismatch")
    images = ReleaseImages.read(directory / IMAGES_NAME)
    if images.source_commit != metadata["commit"]:
        raise ValueError("installed image provenance mismatch")
    return images


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    build = sub.add_parser("create")
    build.add_argument("--source", type=Path, default=Path.cwd())
    build.add_argument("--images", type=Path, required=True)
    build.add_argument("--tag", required=True)
    build.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("verify")
    check.add_argument("bundle", type=Path)
    check.add_argument("--commit")
    check.add_argument("--tag")
    args = parser.parse_args()
    if args.operation == "create":
        create(args.source, args.images, args.tag, args.output)
    else:
        print(
            json.dumps(
                verify(args.bundle, commit=args.commit, tag=args.tag), sort_keys=True
            )
        )


if __name__ == "__main__":
    main()
