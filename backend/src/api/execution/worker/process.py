"""Taskiq process lifecycle and dependency ingress for worker-owned resources."""

import asyncio

from taskiq import TaskiqState

from api.deployment.settings import StartupSettings
from api.operations.worker import start_worker_presence, stop_worker_presence

from .resources import WorkerResources


async def start_worker(state: TaskiqState) -> None:
    settings = await asyncio.to_thread(StartupSettings.from_env)
    resources = await WorkerResources.create(settings)
    state.worker_resources = resources
    try:
        await start_worker_presence(state)
    except BaseException:
        await stop_worker(state)
        raise


async def stop_worker(state: TaskiqState) -> None:
    cleanup = []
    if hasattr(state, "worker_resources"):
        cleanup.append(state.worker_resources.close())
    if hasattr(state, "worker_presence"):
        cleanup.append(stop_worker_presence(state))
    results = await asyncio.gather(*cleanup, return_exceptions=True)
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        raise BaseExceptionGroup("worker process shutdown failed", errors)


def worker_resources(state: TaskiqState) -> WorkerResources:
    resources = getattr(state, "worker_resources", None)
    if not isinstance(resources, WorkerResources) or resources.closing:
        raise RuntimeError("worker resources are not available")
    return resources
