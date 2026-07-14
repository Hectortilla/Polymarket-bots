"""Runtime counters for multiplexed CLI streams."""

from dataclasses import dataclass


@dataclass(slots=True)
class StreamTelemetry:
    queue_depth: int = 0
    peak_queue_depth: int = 0
    book_received_count: int = 0
    book_dropped_count: int = 0

    def enqueued(self) -> None:
        self.queue_depth += 1
        self.peak_queue_depth = max(self.peak_queue_depth, self.queue_depth)

    def dequeued(self) -> None:
        self.queue_depth = max(0, self.queue_depth - 1)

    def book_received(self) -> None:
        self.book_received_count += 1

    def book_dropped(self) -> None:
        self.book_dropped_count += 1

    def reset_queue_depth(self) -> None:
        self.queue_depth = 0

    @property
    def book_drop_ratio(self) -> float:
        if self.book_received_count == 0:
            return 0.0
        return self.book_dropped_count / self.book_received_count
