"""Fixed-shard routing for advisory live telemetry only."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID

LIVE_CHANNEL_PREFIX = "polybot:live:run:"


@dataclass(frozen=True, slots=True)
class LiveShard:
    index: int
    url: str = field(repr=False)


class LiveShardRouter:
    """Route one run consistently to one configured Redis server."""

    def __init__(self, urls: tuple[str, ...]) -> None:
        if not urls or any(not url.strip() for url in urls):
            raise ValueError("live telemetry requires at least one Redis shard URL")
        self._shards = tuple(LiveShard(index, url) for index, url in enumerate(urls))

    @property
    def shards(self) -> tuple[LiveShard, ...]:
        return self._shards

    def shard_for(self, run_id: UUID) -> LiveShard:
        digest = sha256(run_id.bytes).digest()
        return self._shards[int.from_bytes(digest[:8], "big") % len(self._shards)]

    def channel(self, run_id: UUID) -> str:
        return f"{LIVE_CHANNEL_PREFIX}{run_id}"

    def run_from_channel(self, channel: object, shard_index: int) -> UUID | None:
        if isinstance(channel, bytes):
            try:
                channel = channel.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if not isinstance(channel, str) or not channel.startswith(LIVE_CHANNEL_PREFIX):
            return None
        try:
            run_id = UUID(channel.removeprefix(LIVE_CHANNEL_PREFIX))
        except ValueError:
            return None
        return run_id if self.shard_for(run_id).index == shard_index else None
