"""Build a committed release on this laptop, push to GHCR, and save its digests."""

import argparse
import re
from pathlib import Path
from types import MappingProxyType

from scripts import ghcr
from scripts.deployment.buildx import (
    BuildPlatform,
    build_image,
    resolve_image,
)
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.images import APPLICATION_IMAGES, ImageField, ReleaseImages
from scripts.deployment.source import clean_snapshot

DEFAULT_BUILD_PLATFORM = BuildPlatform.AMD64
DEFAULT_POSTGRES_IMAGE = "postgres:17"
DEFAULT_REDIS_IMAGE = "redis:7-alpine"


def publish(
    namespace: str,
    platform: BuildPlatform,
    output: Path,
    postgres_image: str,
    redis_image: str,
    username: str,
) -> None:
    if re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", namespace) is None:
        raise ValueError("namespace must be a lowercase GitHub user or organization")
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists; choose a new release manifest")
    with clean_snapshot() as source:
        output.parent.mkdir(parents=True, exist_ok=True)
        ghcr.login(username)
        references = {
            ImageField.POSTGRES: resolve_image(postgres_image),
            ImageField.REDIS: resolve_image(redis_image),
        }
        for field, component in APPLICATION_IMAGES.items():
            repository = f"{ghcr.REGISTRY}/{namespace}/polybot-{component}"
            references[field] = build_image(source, component, repository, platform)
        images = ReleaseImages(source.commit, MappingProxyType(references))
        write_manifest(output, images.to_values(), replace=False)
    print(
        f"Published {images.source_commit} for {platform.value}. Image manifest: {output.resolve()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--namespace", required=True, help="GitHub user or organization"
    )
    parser.add_argument("--username", required=True, help="GitHub login user")
    parser.add_argument(
        "--platform",
        type=BuildPlatform,
        choices=tuple(BuildPlatform),
        default=DEFAULT_BUILD_PLATFORM,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--redis-image", default=DEFAULT_REDIS_IMAGE)
    args = parser.parse_args()
    publish(
        args.namespace,
        args.platform,
        args.output,
        args.postgres_image,
        args.redis_image,
        args.username,
    )


if __name__ == "__main__":
    main()
