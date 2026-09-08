"""Projected order-book state used during archive replay."""

from __future__ import annotations

from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.errors import MarketDataError
from polybot.polymarket.markets import Market
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
)
from polybot.recording.contracts.records import BookCheckpoint, RecordedEvent


class ProjectedBookReplay:
    """Own normalized projectors, replay baselines, and published snapshots."""

    def __init__(self) -> None:
        self._projectors: dict[str, BookDepthProjector] = {}
        self._books: dict[str, BookSnapshot] = {}
        self._generation_by_token: dict[str, int] = {}
        self._baseline_sequence_by_token: dict[str, int] = {}
        self._bootstrapped_conditions: set[str] = set()

    @property
    def books(self) -> dict[str, BookSnapshot]:
        return self._books.copy()

    def register_market(self, market: Market) -> None:
        self._projectors.setdefault(
            market.condition_id,
            BookDepthProjector((market,)),
        )

    def latest(self, token_id: str) -> BookSnapshot | None:
        return self._books.get(token_id)

    def has_complete_book(self, market: Market) -> bool:
        projector = self._projectors.get(market.condition_id)
        generations = {
            self._generation_by_token.get(token_id) for token_id in market.token_ids
        }
        return (
            projector is not None
            and projector.has_complete_baseline(market.condition_id)
            and None not in generations
            and len(generations) == 1
        )

    def has_bootstrap_evidence(self, condition_id: str | None) -> bool:
        return condition_id in self._bootstrapped_conditions

    def seed_checkpoints(
        self,
        checkpoints: tuple[BookCheckpoint, BookCheckpoint],
    ) -> tuple[str, ...]:
        try:
            staged = []
            for checkpoint in checkpoints:
                condition_id = checkpoint.identity.condition_id
                if condition_id is None:
                    raise BacktestError(
                        BacktestFailureReason.MISSING_MARKET_DATA,
                        "book checkpoint has no condition identity",
                    )
                projector = self._required_projector(condition_id)
                snapshot = projector.preview_baseline(
                    checkpoint.book,
                    condition_id=condition_id,
                    received_at_ms=checkpoint.observed_at_ms,
                )
                staged.append((projector, checkpoint, snapshot))
            for projector, checkpoint, snapshot in staged:
                projector.apply_baseline(
                    checkpoint.book,
                    condition_id=checkpoint.identity.condition_id or "",
                    received_at_ms=checkpoint.observed_at_ms,
                )
                self._books[snapshot.token_id] = snapshot
                self._generation_by_token[snapshot.token_id] = (
                    checkpoint.subscription_generation
                )
                self._baseline_sequence_by_token[snapshot.token_id] = (
                    checkpoint.sequence
                )
            return tuple(
                dict.fromkeys(
                    checkpoint.identity.condition_id
                    for _, checkpoint, _ in staged
                    if checkpoint.identity.condition_id is not None
                )
            )
        except MarketDataError as error:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                str(error),
            ) from error

    def bootstrap_books(
        self,
        markets: tuple[Market, ...],
        *,
        received_at_ms: int,
    ) -> tuple[BookSnapshot, ...]:
        snapshots: list[BookSnapshot] = []
        for market in markets:
            projector = self._required_projector(market.condition_id)
            by_token = {
                snapshot.token_id: snapshot
                for snapshot in projector.snapshots(received_at_ms=received_at_ms)
            }
            snapshots.extend(
                by_token[token_id]
                for token_id in market.token_ids
                if token_id in by_token
            )
        self.publish_many(tuple(snapshots))
        return tuple(snapshots)

    def apply_baseline(
        self,
        event: RecordedEvent,
        payload: BookBaselinePayload,
        condition_id: str,
    ) -> BookSnapshot:
        try:
            snapshot = self._required_projector(condition_id).apply_baseline(
                payload,
                condition_id=condition_id,
                received_at_ms=event.observed_at_ms,
            )
        except MarketDataError as error:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                str(error),
            ) from error
        self._generation_by_token[snapshot.token_id] = event.subscription_generation
        self._baseline_sequence_by_token[snapshot.token_id] = event.sequence
        return snapshot

    def apply_delta(
        self,
        event: RecordedEvent,
        payload: BookDeltaPayload,
        condition_id: str,
    ) -> tuple[BookSnapshot, ...]:
        try:
            return self._required_projector(condition_id).apply_delta(
                payload,
                condition_id=condition_id,
                received_at_ms=event.observed_at_ms,
            )
        except MarketDataError as error:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                str(error),
            ) from error

    def require_delta_generation(
        self,
        event: RecordedEvent,
        payload: BookDeltaPayload,
    ) -> None:
        missing = sorted(
            {
                change.token_id
                for change in payload.changes
                if self._generation_by_token.get(change.token_id)
                != event.subscription_generation
            }
        )
        if missing:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                "book delta has no replayed baseline in subscription generation "
                f"{event.subscription_generation}: {', '.join(missing)}",
            )

    def publish(self, snapshot: BookSnapshot) -> None:
        self._books[snapshot.token_id] = snapshot

    def publish_many(self, snapshots: tuple[BookSnapshot, ...]) -> None:
        for snapshot in snapshots:
            self.publish(snapshot)

    def mark_bootstrapped(self, condition_id: str) -> None:
        self._bootstrapped_conditions.add(condition_id)

    def clear_condition(self, market: Market) -> tuple[str, ...]:
        projector = self._projectors.get(market.condition_id)
        if projector is not None:
            projector.clear()
        for token_id in market.token_ids:
            self._books.pop(token_id, None)
            self._generation_by_token.pop(token_id, None)
            self._baseline_sequence_by_token.pop(token_id, None)
        return market.token_ids

    def baseline_sequence(self, token_id: str) -> int:
        return self._baseline_sequence_by_token.get(token_id, 0)

    def generation(self, token_id: str) -> int | None:
        return self._generation_by_token.get(token_id)

    def recovery_snapshots(
        self,
        market: Market,
        *,
        recovery_after_sequence: int,
        observed_at_ms: int,
    ) -> tuple[BookSnapshot, ...]:
        if any(
            self.baseline_sequence(token_id) <= recovery_after_sequence
            for token_id in market.token_ids
        ):
            return ()
        generations = {self.generation(token_id) for token_id in market.token_ids}
        if None in generations or len(generations) != 1:
            return ()
        projector = self._required_projector(market.condition_id)
        if not projector.has_complete_baseline(market.condition_id):
            return ()
        snapshots_by_token = {
            snapshot.token_id: snapshot
            for snapshot in projector.snapshots(received_at_ms=observed_at_ms)
        }
        if not set(market.token_ids).issubset(snapshots_by_token):
            return ()
        return tuple(snapshots_by_token[token_id] for token_id in market.token_ids)

    def _required_projector(self, condition_id: str) -> BookDepthProjector:
        projector = self._projectors.get(condition_id)
        if projector is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"book data preceded recorded metadata for {condition_id}",
            )
        return projector
