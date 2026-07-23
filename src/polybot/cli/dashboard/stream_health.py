"""Stream throughput, dispatch, bootstrap, and latency metrics for the dashboard."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import ceil
from time import monotonic

from polybot.cli.observability.events import BootstrapPhase
from polybot.cli.streams.contracts import StreamKind

from .health import average, ratio

EVENT_RATE_WINDOW_SECONDS = 10
LATENCY_SAMPLE_LIMIT = 100
HEALTH_SAMPLE_LIMIT = 100


@dataclass(slots=True)
class DashboardStreamHealth:
    """Bounded metrics that summarize the runtime's event and stream flow."""

    stream_counts: dict[StreamKind, int] = field(default_factory=dict)
    wallets_loaded: int = 0
    wallets_total: int | None = None
    markets_loaded: int = 0
    markets_total: int | None = None
    accepted_dispatches: int = 0
    skipped_dispatches: int = 0
    order_count: int = 0
    fill_count: int = 0
    rejected_count: int = 0
    wallet_detection_lags_ms: deque[int] = field(
        default_factory=lambda: deque(maxlen=LATENCY_SAMPLE_LIMIT)
    )
    broker_latencies_ms: deque[int] = field(
        default_factory=lambda: deque(maxlen=LATENCY_SAMPLE_LIMIT)
    )
    book_lags_ms: deque[int] = field(
        default_factory=lambda: deque(maxlen=HEALTH_SAMPLE_LIMIT)
    )
    book_stale_samples: deque[bool] = field(
        default_factory=lambda: deque(maxlen=HEALTH_SAMPLE_LIMIT)
    )
    book_coalescing_samples: deque[tuple[int, int]] = field(
        default_factory=lambda: deque(maxlen=HEALTH_SAMPLE_LIMIT)
    )
    book_received_count: int = 0
    book_coalesced_count: int = 0
    queue_depth: int = 0
    peak_queue_depth: int = 0
    stream_received_monotonic_times: dict[StreamKind, deque[float]] = field(
        default_factory=dict
    )
    stream_dispatched_monotonic_times: dict[StreamKind, deque[float]] = field(
        default_factory=dict
    )
    event_monotonic_times: deque[float] = field(default_factory=deque)

    def remember_event(self, occurred_at_monotonic: float) -> None:
        self.event_monotonic_times.append(occurred_at_monotonic)
        self._trim_event_times(occurred_at_monotonic)

    def record_stream_received(
        self, kind: StreamKind, occurred_at_monotonic: float
    ) -> None:
        self.stream_counts[kind] = self.stream_counts.get(kind, 0) + 1
        self._record_rate(
            self.stream_received_monotonic_times,
            kind,
            occurred_at_monotonic,
        )

    def record_bootstrap(
        self, phase: BootstrapPhase, completed: int, total: int
    ) -> None:
        if phase is BootstrapPhase.WALLETS:
            self.wallets_loaded = completed
            self.wallets_total = total
            return
        self.markets_loaded = completed
        self.markets_total = total

    def record_dispatch(
        self,
        kind: StreamKind,
        *,
        accepted: bool,
        occurred_at_monotonic: float,
    ) -> None:
        if accepted:
            self.accepted_dispatches += 1
        else:
            self.skipped_dispatches += 1
        self._record_rate(
            self.stream_dispatched_monotonic_times,
            kind,
            occurred_at_monotonic,
        )

    def record_order(self) -> None:
        self.order_count += 1

    def record_fill(self, latency_ms: int, *, rejected: bool) -> None:
        self.broker_latencies_ms.append(latency_ms)
        if rejected:
            self.rejected_count += 1
            return
        self.fill_count += 1

    def record_wallet_detection_lag(self, lag_ms: int) -> None:
        self.wallet_detection_lags_ms.append(lag_ms)

    def record_health(
        self,
        *,
        queue_depth: int,
        peak_queue_depth: int,
        book_dispatch_lag_ms: int | None,
        book_stale: bool,
        book_received_count: int,
        book_coalesced_count: int,
    ) -> None:
        self.queue_depth = queue_depth
        self.peak_queue_depth = max(self.peak_queue_depth, peak_queue_depth)
        self._record_book_coalescing_counts(
            book_received_count,
            book_coalesced_count,
        )
        if book_dispatch_lag_ms is not None:
            self.book_lags_ms.append(book_dispatch_lag_ms)
            self.book_stale_samples.append(book_stale)

    def event_rate(self, now_monotonic: float | None = None) -> float:
        current = monotonic() if now_monotonic is None else now_monotonic
        self._trim_event_times(current)
        return len(self.event_monotonic_times) / EVENT_RATE_WINDOW_SECONDS

    def stream_rate(self, kind: StreamKind, *, received: bool) -> float:
        samples = (
            self.stream_received_monotonic_times
            if received
            else self.stream_dispatched_monotonic_times
        ).get(kind)
        if not samples:
            return 0.0
        current = monotonic()
        self._trim_times(samples, current)
        return len(samples) / EVENT_RATE_WINDOW_SECONDS

    def average_wallet_lag_ms(self) -> int | None:
        return average(self.wallet_detection_lags_ms)

    def average_broker_latency_ms(self) -> int | None:
        return average(self.broker_latencies_ms)

    def latest_book_lag_ms(self) -> int | None:
        return self.book_lags_ms[-1] if self.book_lags_ms else None

    def book_lag_percentile(self, percentile: float) -> int | None:
        if not self.book_lags_ms:
            return None
        values = sorted(self.book_lags_ms)
        index = min(len(values) - 1, max(0, ceil(len(values) * percentile) - 1))
        return values[index]

    def maximum_book_lag_ms(self) -> int | None:
        return max(self.book_lags_ms) if self.book_lags_ms else None

    def stale_ratio(self) -> float:
        return ratio(sum(self.book_stale_samples), len(self.book_stale_samples))

    def cumulative_book_coalescing_ratio(self) -> float:
        return ratio(self.book_coalesced_count, self.book_received_count)

    def recent_book_coalescing_ratio(self) -> float:
        received = sum(sample[0] for sample in self.book_coalescing_samples)
        coalesced = sum(sample[1] for sample in self.book_coalescing_samples)
        return ratio(coalesced, received)

    def _record_book_coalescing_counts(
        self, received_count: int, coalesced_count: int
    ) -> None:
        if (
            received_count < self.book_received_count
            or coalesced_count < self.book_coalesced_count
        ):
            return
        received_delta = received_count - self.book_received_count
        coalesced_delta = coalesced_count - self.book_coalesced_count
        self.book_received_count = received_count
        self.book_coalesced_count = coalesced_count
        if received_delta:
            self.book_coalescing_samples.append((received_delta, coalesced_delta))

    def _record_rate(
        self,
        target: dict[StreamKind, deque[float]],
        kind: StreamKind,
        occurred_at_monotonic: float,
    ) -> None:
        samples = target.setdefault(kind, deque())
        samples.append(occurred_at_monotonic)
        self._trim_times(samples, occurred_at_monotonic)

    def _trim_event_times(self, now_monotonic: float) -> None:
        self._trim_times(self.event_monotonic_times, now_monotonic)

    @staticmethod
    def _trim_times(samples: deque[float], now_monotonic: float) -> None:
        cutoff = now_monotonic - EVENT_RATE_WINDOW_SECONDS
        while samples and samples[0] < cutoff:
            samples.popleft()
