import asyncio
from threading import Event, Lock

from polybot.async_io import run_blocking


def test_run_blocking_uses_a_bounded_worker_pool() -> None:
    call_count = 64
    release = Event()
    state_lock = Lock()
    active_workers = 0
    peak_workers = 0

    def block_until_released() -> None:
        nonlocal active_workers, peak_workers
        with state_lock:
            active_workers += 1
            peak_workers = max(peak_workers, active_workers)
        try:
            release.wait(timeout=1)
        finally:
            with state_lock:
                active_workers -= 1

    async def run() -> None:
        tasks = [
            asyncio.create_task(run_blocking(block_until_released))
            for _ in range(call_count)
        ]
        try:
            await asyncio.sleep(0.05)
        finally:
            release.set()
        await asyncio.gather(*tasks)

    asyncio.run(run())

    assert 0 < peak_workers <= 32
