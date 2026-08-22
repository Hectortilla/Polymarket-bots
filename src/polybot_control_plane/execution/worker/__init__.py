"""Taskiq worker entrypoint for one durable paper run."""

from uuid import UUID

from .resources import run_with_worker_resources


async def execute_run(run_id: UUID) -> None:
    await run_with_worker_resources(run_id)
