"""Safe reads of listed source members inside an installed release."""

from pathlib import Path

from scripts.deployment.bundle.metadata import BundleMetadata
from scripts.private_files import read_regular


def read_installed_contents(
    directory: Path, metadata: BundleMetadata
) -> dict[str, bytes]:
    root = directory.resolve(strict=True)
    contents = {}
    for name in metadata.files:
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("installed release content mismatch")
        contents[name] = read_regular(path)
    return contents
