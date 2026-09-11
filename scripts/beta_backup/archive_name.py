"""Completed archive names bind snapshot time and content checksum in one format."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from polybot.persistence.hashing import SHA256_ALGORITHM

BACKUP_ARCHIVE_PREFIX = "polybot-"
BACKUP_ARCHIVE_SUFFIX = ".dump.age"


ARCHIVE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
ARCHIVE_CHECKSUM_HEX_LENGTH = hashlib.new(SHA256_ALGORITHM).digest_size * 2


@dataclass(frozen=True)
class ArchiveName:
    snapshot_started_at: datetime
    identifier: UUID
    checksum: str

    def format(self) -> str:
        timestamp = self.snapshot_started_at.strftime(ARCHIVE_TIMESTAMP_FORMAT)
        return f"{BACKUP_ARCHIVE_PREFIX}{timestamp}-{self.identifier.hex}-{self.checksum}{BACKUP_ARCHIVE_SUFFIX}"

    @classmethod
    def parse(cls, name: str) -> "ArchiveName | None":
        if not name.startswith(BACKUP_ARCHIVE_PREFIX) or not name.endswith(
            BACKUP_ARCHIVE_SUFFIX
        ):
            return None
        parts = (
            name.removeprefix(BACKUP_ARCHIVE_PREFIX)
            .removesuffix(BACKUP_ARCHIVE_SUFFIX)
            .split("-")
        )
        if len(parts) != 3:
            return None
        timestamp, identifier, checksum = parts
        if len(checksum) != ARCHIVE_CHECKSUM_HEX_LENGTH or any(
            character not in "0123456789abcdef" for character in checksum
        ):
            return None
        try:
            parsed = cls(
                datetime.strptime(timestamp, ARCHIVE_TIMESTAMP_FORMAT).replace(
                    tzinfo=timezone.utc
                ),
                UUID(hex=identifier),
                checksum,
            )
        except ValueError:
            return None
        return parsed if parsed.format() == name else None
