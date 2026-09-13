"""Regular-member tar I/O for release bundles."""

import io
import tarfile
from collections.abc import Mapping
from pathlib import Path

from scripts.deployment.bundle.contracts import validate_member_name


def read_archive_contents(bundle_archive_path: Path) -> dict[str, bytes]:
    with tarfile.open(bundle_archive_path, "r:gz") as archive:
        contents = {}
        for member in archive.getmembers():
            name = validate_member_name(member.name)
            if name in contents:
                raise ValueError("duplicate bundle member")
            if not member.isfile():
                raise ValueError("unsafe bundle member")
            contents[name] = archive.extractfile(member).read()
        return contents


def write_archive_contents(output: Path, contents: Mapping[str, bytes]) -> None:
    with (
        output.open("xb") as destination,
        tarfile.open(fileobj=destination, mode="w:gz") as archive,
    ):
        for name, content in sorted(contents.items()):
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(content), 0o644
            archive.addfile(member, io.BytesIO(content))
