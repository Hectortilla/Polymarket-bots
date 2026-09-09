"""Recovery service retry and bounded signal handling without external services."""

import asyncio
import logging
import signal
from unittest.mock import AsyncMock, patch

from api.deployment.settings import StartupSettings
from api.execution.recovery import __main__ as recovery_process


def test_recovery_process_retries_database_outage_and_handles_termination(caplog):
    async def scenario():
        callbacks = {}
        calls = 0
        engine = AsyncMock()

        async def tick():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("database unavailable")
            callbacks[signal.SIGTERM]()

        recovery = AsyncMock()
        recovery.tick.side_effect = tick
        loop = asyncio.get_running_loop()
        with (
            patch.object(
                loop,
                "add_signal_handler",
                side_effect=lambda sig, callback: callbacks.update({sig: callback}),
            ),
            patch.object(
                recovery_process,
                "create_worker_database",
                return_value=(engine, object()),
            ),
            patch.object(recovery_process, "RunRecovery", return_value=recovery),
            patch.object(recovery_process, "DELIVERY_RETRY_SECONDS", 0.001),
        ):
            await asyncio.wait_for(
                recovery_process.serve_recovery(
                    StartupSettings(database_url="fixture", redis_url="fixture")
                ),
                timeout=1,
            )
        assert calls == 2
        engine.dispose.assert_awaited_once()

    with caplog.at_level(logging.ERROR):
        asyncio.run(scenario())
    assert "retrying after outage" in caplog.text
