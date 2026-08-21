"""The single launch seam shared by HTTP and worker implementations."""

from typing import Protocol
from uuid import UUID


class RunLauncher(Protocol):
    async def launch(self, run_id: UUID) -> None: ...
