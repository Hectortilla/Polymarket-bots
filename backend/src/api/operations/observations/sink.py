"""Nonblocking bounded operational log publication, with a dedicated I/O thread."""

import json
import logging
from dataclasses import asdict
from queue import Full, Queue
from threading import Thread

from api.operations.observations.contracts import (
    LogOverflowObservation,
    OperationalRecord,
)

OPERATION_LOGGER_NAME = "polybot.operations"
MAX_QUEUED_OPERATION_RECORDS = 1024


class OperationLog:
    def __init__(self) -> None:
        self._records: Queue[OperationalRecord] = Queue(MAX_QUEUED_OPERATION_RECORDS)
        self._dropped = 0
        self._thread = Thread(
            target=self._write_records, daemon=True, name="operation-log"
        )
        self._thread.start()

    def emit(self, record: OperationalRecord) -> None:
        # A blocked sink must not block requests, lease heartbeats or paper fills.
        try:
            if self._dropped:
                self._records.put_nowait(LogOverflowObservation(self._dropped))
                self._dropped = 0
            self._records.put_nowait(record)
        except Full:
            self._dropped += 1

    def flush(self) -> None:
        """Synchronous drain for tests/CLI shutdown; never call on an event loop."""
        self._records.join()

    def _write_records(self) -> None:
        logger = logging.getLogger(OPERATION_LOGGER_NAME)
        while True:
            record = self._records.get()
            try:
                logger.warning(json.dumps(asdict(record), sort_keys=True))
            finally:
                self._records.task_done()


OPERATION_LOG = OperationLog()
