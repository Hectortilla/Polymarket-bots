"""Exclusive CSV output ownership for one performance result directory."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from polybot.performance.contracts.files import (
    EQUITY_FIELDS,
    EQUITY_FILE_NAME,
    ORDERS_FILE_NAME,
    ORDER_FIELDS,
)

from .errors import PerformanceArtifactStateError, PerformanceOutputExistsError


class PerformanceCsvOutput:
    """Create, append, flush, and close the two streamed CSV artifacts."""

    def __init__(self, results_dir: Path) -> None:
        self._results_dir = results_dir
        self._equity_file: TextIO | None = None
        self._orders_file: TextIO | None = None
        self._equity_writer: csv.DictWriter[str] | None = None
        self._orders_writer: csv.DictWriter[str] | None = None
        self._create()

    def write_equity(
        self,
        row: Mapping[str, object],
        *,
        flush: bool = True,
    ) -> None:
        self._required_equity_writer().writerow(row)
        if flush:
            self.flush_equity()

    def write_order(self, row: Mapping[str, object]) -> None:
        self._required_orders_writer().writerow(row)
        self.flush_orders()

    def flush_equity(self) -> None:
        if self._equity_file is not None and not self._equity_file.closed:
            self._equity_file.flush()

    def flush_orders(self) -> None:
        if self._orders_file is not None and not self._orders_file.closed:
            self._orders_file.flush()

    def close(self) -> None:
        for output in (self._equity_file, self._orders_file):
            if output is not None and not output.closed:
                output.close()

    def _create(self) -> None:
        try:
            self._results_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise PerformanceOutputExistsError(
                "performance results directory already exists: "
                f"{self._results_dir}"
            ) from error
        try:
            self._equity_file = (self._results_dir / EQUITY_FILE_NAME).open(
                "x",
                encoding="utf-8",
                newline="",
            )
            self._orders_file = (self._results_dir / ORDERS_FILE_NAME).open(
                "x",
                encoding="utf-8",
                newline="",
            )
            self._equity_writer = csv.DictWriter(
                self._equity_file,
                fieldnames=EQUITY_FIELDS,
            )
            self._orders_writer = csv.DictWriter(
                self._orders_file,
                fieldnames=ORDER_FIELDS,
            )
            self._equity_writer.writeheader()
            self._orders_writer.writeheader()
            self.flush_equity()
            self.flush_orders()
        except Exception:
            self.close()
            raise

    def _required_equity_writer(self) -> csv.DictWriter[str]:
        writer = self._equity_writer
        if writer is None or self._equity_file is None or self._equity_file.closed:
            raise PerformanceArtifactStateError("performance equity output is closed")
        return writer

    def _required_orders_writer(self) -> csv.DictWriter[str]:
        writer = self._orders_writer
        if writer is None or self._orders_file is None or self._orders_file.closed:
            raise PerformanceArtifactStateError("performance orders output is closed")
        return writer
