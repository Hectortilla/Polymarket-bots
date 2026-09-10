"""Cleanup failures remain visible, retryable and supervised."""

import asyncio
from unittest.mock import patch

from api.lifecycle.maintenance import DataMaintenance
from api.operations.observations.contracts import FailureObservation, Observation


def test_maintenance_failure_is_reported_and_retried():
    async def scenario():
        retried = asyncio.Event()
        attempts = 0

        async def tick():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("private dependency text")
            retried.set()

        maintenance = DataMaintenance(None)
        with (
            patch.object(maintenance, "tick", side_effect=tick),
            patch("api.lifecycle.maintenance.CLEANUP_INTERVAL_SECONDS", 0.001),
            patch("api.lifecycle.maintenance.OPERATION_LOG") as log,
        ):
            task = asyncio.create_task(maintenance.serve())
            await asyncio.wait_for(retried.wait(), 1)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert attempts >= 2
            log.emit.assert_called_once_with(
                FailureObservation(Observation.DATA_MAINTENANCE_FAILED)
            )

    asyncio.run(scenario())
