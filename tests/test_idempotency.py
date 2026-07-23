import asyncio
import multiprocessing
import os
from pathlib import Path

from polybot.execution.paper.idempotency import FileSourceIdempotencyStore


def _claim_in_process(path: str, ready, results) -> None:
    ready.get()
    results.put(FileSourceIdempotencyStore(path).claim("leader\\0trade-1"))


def test_file_source_idempotency_store_survives_reopen(tmp_path) -> None:
    path = tmp_path / "source-ids"

    async def run() -> tuple[bool, bool, bool]:
        first = FileSourceIdempotencyStore(path)
        second = FileSourceIdempotencyStore(path)
        claimed = first.claim("leader\\0trade-1")
        duplicate = second.claim("leader\\0trade-1")
        first.release("leader\\0trade-1")
        available_again = second.claim("leader\\0trade-1")
        return claimed, duplicate, available_again

    assert asyncio.run(run()) == (True, False, True)


def test_file_source_idempotency_store_syncs_claims_before_unlocking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    synchronized_descriptors: list[int] = []
    monkeypatch.setattr(os, "fsync", synchronized_descriptors.append)

    assert FileSourceIdempotencyStore(tmp_path / "source-ids").claim("source")

    # The claim file and its new directory entry are both durable before unlock.
    assert len(synchronized_descriptors) == 2


def test_file_source_idempotency_store_allows_one_concurrent_process_claim(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source-ids"
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    results = context.Queue()
    processes = [
        context.Process(target=_claim_in_process, args=(str(path), ready, results))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    ready.put(None)
    ready.put(None)
    claims = sorted(results.get(timeout=10) for _ in processes)
    for process in processes:
        process.join(timeout=10)
    assert claims == [False, True]
    assert all(process.exitcode == 0 for process in processes)
