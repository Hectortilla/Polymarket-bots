"""Taskiq delivery entrypoint that drains eligible durable paper runs."""

from uuid import UUID

from .resources import drain_queued_runs_with_worker_resources


async def execute_run(run_id: UUID) -> None:
    await drain_queued_runs_with_worker_resources()
