from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from polybot.framework.events.books import BookSnapshot

BTC_FIVE_MINUTE_SLUG_PREFIX = "btc-updown-5m"
class MomentumDirection(StrEnum):
    UP = "Up"
    DOWN = "Down"


class MomentumExitReason(StrEnum):
    EXPIRY = "btc_5m_expiry_exit"
    STOP = "btc_5m_stop_exit"
    TARGET = "btc_5m_target_exit"
    REVERSAL = "btc_5m_reversal_exit"
    TIME = "btc_5m_time_exit"


UP_OUTCOME = MomentumDirection.UP
DOWN_OUTCOME = MomentumDirection.DOWN
MOMENTUM_ENTRY_REASON = "btc_5m_probability_momentum"
EXPIRY_EXIT_REASON = MomentumExitReason.EXPIRY
STOP_EXIT_REASON = MomentumExitReason.STOP
TARGET_EXIT_REASON = MomentumExitReason.TARGET
REVERSAL_EXIT_REASON = MomentumExitReason.REVERSAL
TIME_EXIT_REASON = MomentumExitReason.TIME


@dataclass(frozen=True, slots=True)
class MomentumSettings:
    """Readable strategy and risk parameters, expressed in token-price units."""

    bucket_seconds: int = 300
    order_size: Decimal = Decimal("5")
    sample_interval_ms: int = 750
    paired_book_max_skew_ms: int = 1_500
    paired_book_max_age_ms: int = 5_000
    momentum_lookback: int = 6
    warmup_samples: int = 12
    fast_ema_alpha: Decimal = Decimal("0.40")
    slow_ema_alpha: Decimal = Decimal("0.12")
    minimum_trend: Decimal = Decimal("0.008")
    minimum_momentum: Decimal = Decimal("0.02")
    noise_trend_multiple: Decimal = Decimal("1.25")
    noise_momentum_multiple: Decimal = Decimal("2.5")
    minimum_imbalance: Decimal = Decimal("0.10")
    maximum_spread: Decimal = Decimal("0.04")
    minimum_depth: Decimal = Decimal("10")
    minimum_entry_price: Decimal = Decimal("0.20")
    maximum_entry_price: Decimal = Decimal("0.80")
    entry_delay_ms: int = 20_000
    entry_cutoff_ms: int = 45_000
    force_exit_ms: int = 15_000
    maximum_hold_ms: int = 60_000
    stop_loss: Decimal = Decimal("0.05")
    take_profit: Decimal = Decimal("0.08")
    reversal_trend: Decimal = Decimal("0.006")
    cooldown_ms: int = 10_000

    def __post_init__(self) -> None:
        if self.bucket_seconds <= 0 or self.order_size <= 0:
            raise ValueError("bucket_seconds and order_size must be positive")
        if (
            self.sample_interval_ms <= 0
            or self.paired_book_max_skew_ms < 0
            or self.paired_book_max_age_ms < 0
        ):
            raise ValueError("sampling interval must be positive and book ages nonnegative")
        if (
            self.momentum_lookback <= 0
            or self.warmup_samples <= self.momentum_lookback
        ):
            raise ValueError("warmup_samples must exceed momentum_lookback")
        if not 0 < self.slow_ema_alpha < self.fast_ema_alpha <= 1:
            raise ValueError("EMA alphas must satisfy 0 < slow < fast <= 1")
        if not 0 < self.minimum_entry_price < self.maximum_entry_price < 1:
            raise ValueError("entry prices must be ordered within (0, 1)")
        if self.force_exit_ms >= self.entry_cutoff_ms:
            raise ValueError("force_exit_ms must be earlier than the entry cutoff")
        if min(
            self.entry_delay_ms,
            self.force_exit_ms,
            self.maximum_hold_ms,
            self.cooldown_ms,
        ) < 0:
            raise ValueError("strategy time windows must be nonnegative")
        if self.entry_delay_ms + self.entry_cutoff_ms >= self.bucket_seconds * 1_000:
            raise ValueError("entry buffers must leave time for trading")
        risk_values = (
            self.minimum_trend,
            self.minimum_momentum,
            self.noise_trend_multiple,
            self.noise_momentum_multiple,
            self.maximum_spread,
            self.minimum_depth,
            self.stop_loss,
            self.take_profit,
            self.reversal_trend,
        )
        if any(not value.is_finite() or value < 0 for value in risk_values):
            raise ValueError("strategy thresholds must be finite and nonnegative")
        if not 0 <= self.minimum_imbalance <= 1:
            raise ValueError("minimum_imbalance must be within [0, 1]")

    def direction(self, metrics: TrendMetrics) -> MomentumDirection | None:
        trend_floor = max(
            self.minimum_trend,
            metrics.noise * self.noise_trend_multiple,
        )
        momentum_floor = max(
            self.minimum_momentum,
            metrics.noise * self.noise_momentum_multiple,
        )
        if metrics.trend >= trend_floor and metrics.momentum >= momentum_floor:
            return MomentumDirection.UP
        if metrics.trend <= -trend_floor and metrics.momentum <= -momentum_floor:
            return MomentumDirection.DOWN
        return None

    def entry_quote_is_safe(
        self,
        quote: BookQuote | None,
        other_quote: BookQuote | None,
    ) -> bool:
        if quote is None or other_quote is None:
            return False
        return (
            quote.spread <= self.maximum_spread
            and other_quote.spread <= self.maximum_spread
            and quote.bid_depth >= self.minimum_depth
            and quote.ask_depth >= self.minimum_depth
            and quote.imbalance >= self.minimum_imbalance
            and self.minimum_entry_price <= quote.best_ask <= self.maximum_entry_price
        )

    def exit_reason(
        self,
        position: OpenPosition,
        *,
        best_bid: Decimal,
        now_ms: int,
        current_condition_id: str | None,
        metrics: TrendMetrics | None,
    ) -> MomentumExitReason | None:
        if position.bucket_end_ms - now_ms <= self.force_exit_ms:
            return MomentumExitReason.EXPIRY
        if best_bid <= position.average_price - self.stop_loss:
            return MomentumExitReason.STOP
        if best_bid >= position.average_price + self.take_profit:
            return MomentumExitReason.TARGET
        if now_ms - position.opened_at_ms >= self.maximum_hold_ms:
            return MomentumExitReason.TIME
        if current_condition_id != position.condition_id or metrics is None:
            return None
        if (
            position.outcome is MomentumDirection.UP
            and metrics.trend <= -self.reversal_trend
        ) or (
            position.outcome is MomentumDirection.DOWN
            and metrics.trend >= self.reversal_trend
        ):
            return MomentumExitReason.REVERSAL
        return None


@dataclass(frozen=True, slots=True)
class BookQuote:
    best_bid: Decimal
    best_ask: Decimal
    best_ask_size: Decimal
    microprice: Decimal
    spread: Decimal
    bid_depth: Decimal
    ask_depth: Decimal
    imbalance: Decimal

    @classmethod
    def from_book(cls, book: BookSnapshot) -> BookQuote | None:
        if not book.bids or not book.asks:
            return None
        bids = sorted(book.bids, key=lambda level: level.price, reverse=True)
        asks = sorted(book.asks, key=lambda level: level.price)
        best_bid, best_ask = bids[0], asks[0]
        best_size = best_bid.size + best_ask.size
        if best_size <= 0:
            return None
        bid_depth = sum((level.size for level in bids[:3]), Decimal("0"))
        ask_depth = sum((level.size for level in asks[:3]), Decimal("0"))
        total_depth = bid_depth + ask_depth
        if total_depth <= 0:
            return None
        return cls(
            best_bid=best_bid.price,
            best_ask=best_ask.price,
            best_ask_size=best_ask.size,
            microprice=(
                best_ask.price * best_bid.size + best_bid.price * best_ask.size
            )
            / best_size,
            spread=best_ask.price - best_bid.price,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            imbalance=(bid_depth - ask_depth) / total_depth,
        )


@dataclass(frozen=True, slots=True)
class TrendMetrics:
    trend: Decimal
    momentum: Decimal
    noise: Decimal


@dataclass(frozen=True, slots=True)
class ProbabilityObservation:
    trend: ProbabilityTrend
    metrics: TrendMetrics | None


@dataclass(frozen=True, slots=True)
class ProbabilityTrend:
    """EMA trend plus rate-of-change, scaled by recent absolute movement."""

    settings: MomentumSettings
    history: tuple[Decimal, ...] = ()
    fast_ema: Decimal | None = None
    slow_ema: Decimal | None = None

    def after_observation(self, probability: Decimal) -> ProbabilityObservation:
        history = (*self.history, probability)[-(self.settings.warmup_samples * 2) :]
        fast_ema = self._next_ema(
            self.fast_ema, probability, self.settings.fast_ema_alpha
        )
        slow_ema = self._next_ema(
            self.slow_ema, probability, self.settings.slow_ema_alpha
        )
        next_trend = ProbabilityTrend(self.settings, history, fast_ema, slow_ema)
        if len(history) < self.settings.warmup_samples:
            return ProbabilityObservation(next_trend, None)
        recent = history[-(self.settings.momentum_lookback + 1) :]
        moves = tuple(
            abs(current - previous)
            for previous, current in zip(recent, recent[1:])
        )
        assert fast_ema is not None and slow_ema is not None
        return ProbabilityObservation(next_trend, TrendMetrics(
            trend=fast_ema - slow_ema,
            momentum=recent[-1] - recent[0],
            noise=sum(moves, Decimal("0")) / len(moves),
        ))

    @staticmethod
    def _next_ema(previous: Decimal | None, value: Decimal, alpha: Decimal) -> Decimal:
        if previous is None:
            return value
        return alpha * value + (Decimal("1") - alpha) * previous


@dataclass(frozen=True, slots=True)
class BucketTiming:
    elapsed_ms: int
    remaining_ms: int
    bucket_end_ms: int

    @classmethod
    def at(cls, settings: MomentumSettings, now_ms: int) -> BucketTiming:
        bucket_ms = settings.bucket_seconds * 1_000
        elapsed_ms = now_ms % bucket_ms
        return cls(
            elapsed_ms=elapsed_ms,
            remaining_ms=bucket_ms - elapsed_ms,
            bucket_end_ms=now_ms - elapsed_ms + bucket_ms,
        )

    def allows_entry(self, settings: MomentumSettings) -> bool:
        return (
            self.elapsed_ms >= settings.entry_delay_ms
            and self.remaining_ms > settings.entry_cutoff_ms
        )


@dataclass(frozen=True, slots=True)
class OpenPosition:
    token_id: str
    outcome: MomentumDirection
    condition_id: str
    market_slug: str
    size: Decimal
    average_price: Decimal
    opened_at_ms: int
    bucket_end_ms: int
