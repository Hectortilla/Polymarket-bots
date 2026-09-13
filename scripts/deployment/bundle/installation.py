"""A verified bundle inside this host's immutable release store."""

from dataclasses import dataclass
from pathlib import Path

from scripts.deployment.bundle import ReleaseBundle
from scripts.deployment.images import ReleaseImages
from scripts.deployment.paths import (
    CURRENT_RELEASE_NAME,
    RELEASES_DIRECTORY_NAME,
    SOURCE_COMPOSE_PATH,
)
from scripts.private_files import read_regular


@dataclass(frozen=True)
class InstalledBundle:
    directory: Path
    release: ReleaseBundle
    compose_yaml: bytes

    @classmethod
    def read(cls, directory: Path, app_directory: Path) -> "InstalledBundle":
        releases_directory = app_directory.resolve() / RELEASES_DIRECTORY_NAME
        if (
            directory.is_symlink()
            or releases_directory.is_symlink()
            or directory.resolve().parent != releases_directory.resolve()
        ):
            raise ValueError(
                "candidate bundle must be installed inside the release directory"
            )
        release = ReleaseBundle.from_directory(directory)
        return cls(
            directory.resolve(), release, read_regular(directory / SOURCE_COMPOSE_PATH)
        )

    def require_images(self, images: ReleaseImages) -> None:
        if self.release.images != images:
            raise ValueError("installed bundle differs from runtime images")

    def is_current(self, app_directory: Path) -> bool:
        current = app_directory / CURRENT_RELEASE_NAME
        return current.is_symlink() and current.resolve() == self.directory

    def require_current(self, app_directory: Path) -> None:
        if not self.is_current(app_directory):
            raise ValueError("active release pointer differs from runtime bundle")
