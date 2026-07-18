"""Time-aware market metadata and projected order books for replay."""

from __future__ import annotations

from dataclasses import dataclass, replace

from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.errors import MarketDataError
from polybot.polymarket.types import Market, MarketOutcome
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookCheckpoint,
    BookDeltaPayload,
    CoverageGapPayload,
    MarketMetadataPayload,
    PublicTradePayload,
    RecordedEvent,
    ResolutionPayload,
    TickSizeChangePayload,
)


@dataclass(frozen=True, slots=True)
class AppliedArchiveEvent:
    books: tuple[BookSnapshot, ...] = ()
    resolution: MarketResolutionEvent | None = None


class ArchiveMarketState:
    def __init__(self) -> None:
        self._markets_by_condition: dict[str, Market] = {}
        self._condition_by_slug: dict[str, str] = {}
        self._condition_by_token: dict[str, str] = {}
        self._projectors: dict[str, BookDepthProjector] = {}
        self._books: dict[str, BookSnapshot] = {}
        self._generation_by_token: dict[str, int] = {}
        self._resolved_conditions: set[str] = set()

    @property
    def markets(self) -> tuple[Market, ...]:
        return tuple(self._markets_by_condition.values())

    @property
    def market_slugs(self) -> frozenset[str]:
        return frozenset(self._condition_by_slug)

    @property
    def books(self) -> dict[str, BookSnapshot]:
        return self._books.copy()

    def has_complete_book(self, market_slug: str) -> bool:
        market = self.market_for_slug(market_slug)
        if market is None or market.resolved:
            return False
        projector = self._projectors.get(market.condition_id)
        generations = {
            self._generation_by_token.get(token_id)
            for token_id in market.token_ids
        }
        return (
            projector is not None
            and set(market.token_ids).issubset(projector.baseline_token_ids)
            and None not in generations
            and len(generations) == 1
        )

    def market_for_slug(self, slug: str) -> Market | None:
        condition_id = self._condition_by_slug.get(slug)
        return (
            None
            if condition_id is None
            else self._markets_by_condition.get(condition_id)
        )

    async def find_by_slug(self, slug: str) -> Market | None:
        return self.market_for_slug(slug)

    async def latest(self, token_id: str) -> BookSnapshot | None:
        condition_id = self._condition_by_token.get(token_id)
        if condition_id in self._resolved_conditions:
            return None
        return self._books.get(token_id)

    def add_metadata(self, payload: MarketMetadataPayload) -> Market:
        market = _market_from_metadata(payload)
        previous = self._markets_by_condition.get(market.condition_id)
        if previous is not None and (
            previous.slug != market.slug or previous.token_ids != market.token_ids
        ):
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"recorded metadata changed immutable identity for {market.condition_id}",
            )
        self._markets_by_condition[market.condition_id] = market
        self._condition_by_slug[market.slug] = market.condition_id
        for token_id in market.token_ids:
            existing = self._condition_by_token.get(token_id)
            if existing is not None and existing != market.condition_id:
                raise BacktestError(
                    BacktestFailureReason.MISSING_MARKET_DATA,
                    f"token ID maps to multiple recorded markets: {token_id}",
                )
            self._condition_by_token[token_id] = market.condition_id
        self._projectors.setdefault(
            market.condition_id,
            BookDepthProjector((market,)),
        )
        if market.resolved:
            self._resolved_conditions.add(market.condition_id)
        return market

    def seed_checkpoints(
        self,
        checkpoints: tuple[BookCheckpoint, BookCheckpoint],
    ) -> None:
        try:
            for checkpoint in checkpoints:
                condition_id = checkpoint.identity.condition_id
                if condition_id is None:
                    raise BacktestError(
                        BacktestFailureReason.MISSING_MARKET_DATA,
                        "book checkpoint has no condition identity",
                    )
                projector = self._required_projector(condition_id)
                snapshot = projector.apply_baseline(
                    checkpoint.book,
                    condition_id=condition_id,
                    received_at_ms=checkpoint.observed_at_ms,
                )
                self._books[snapshot.token_id] = snapshot
                self._generation_by_token[snapshot.token_id] = (
                    checkpoint.subscription_generation
                )
        except MarketDataError as error:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                str(error),
            ) from error

    def bootstrap_books(
        self,
        market_slugs: set[str] | frozenset[str],
        *,
        received_at_ms: int,
    ) -> tuple[BookSnapshot, ...]:
        snapshots: list[BookSnapshot] = []
        for slug in sorted(market_slugs):
            market = self.market_for_slug(slug)
            if market is None or market.condition_id in self._resolved_conditions:
                continue
            projector = self._projectors[market.condition_id]
            by_token = {
                snapshot.token_id: snapshot
                for snapshot in projector.snapshots(received_at_ms=received_at_ms)
            }
            snapshots.extend(
                by_token[token_id]
                for token_id in market.token_ids
                if token_id in by_token
            )
        for snapshot in snapshots:
            self._books[snapshot.token_id] = snapshot
        return tuple(snapshots)

    def apply(self, event: RecordedEvent) -> AppliedArchiveEvent:
        payload = event.payload
        if isinstance(payload, MarketMetadataPayload):
            self.add_metadata(payload)
            return AppliedArchiveEvent()
        if isinstance(payload, CoverageGapPayload):
            raise BacktestError(
                BacktestFailureReason.COVERAGE_GAP,
                f"selected replay encountered coverage gap: {payload.reason}",
            )
        identity = event.identity
        condition_id = None if identity is None else identity.condition_id
        if condition_id is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"recorded event {event.sequence} has no condition identity",
            )
        if isinstance(payload, BookBaselinePayload):
            snapshot = self._apply_baseline(event, payload, condition_id)
            self._books[snapshot.token_id] = snapshot
            self._generation_by_token[snapshot.token_id] = (
                event.subscription_generation
            )
            return AppliedArchiveEvent(books=(snapshot,))
        if isinstance(payload, BookDeltaPayload):
            self._require_delta_generation(event, payload)
            snapshots = self._apply_delta(event, payload, condition_id)
            for snapshot in snapshots:
                self._books[snapshot.token_id] = snapshot
            return AppliedArchiveEvent(books=snapshots)
        if isinstance(payload, TickSizeChangePayload):
            market = self._required_market(condition_id)
            self._markets_by_condition[condition_id] = replace(
                market,
                minimum_tick_size=payload.new_tick_size,
            )
            return AppliedArchiveEvent()
        if isinstance(payload, PublicTradePayload):
            return AppliedArchiveEvent()
        if isinstance(payload, ResolutionPayload):
            market = self._required_market(condition_id)
            updated = replace(
                market,
                resolved=True,
                winning_token_id=payload.winning_token_id,
                winning_outcome=payload.winning_outcome,
            )
            self._markets_by_condition[condition_id] = updated
            self._resolved_conditions.add(condition_id)
            return AppliedArchiveEvent(
                resolution=MarketResolutionEvent(
                    condition_id=condition_id,
                    market_slug=market.slug,
                    token_ids=payload.token_ids,
                    winning_token_id=payload.winning_token_id,
                    winning_outcome=payload.winning_outcome,
                    resolved_at_ms=event.observed_at_ms,
                    source=payload.source,
                )
            )
        raise TypeError(f"unsupported recorded payload: {type(payload).__name__}")

    def _apply_baseline(
        self,
        event: RecordedEvent,
        payload: BookBaselinePayload,
        condition_id: str,
    ) -> BookSnapshot:
        try:
            return self._required_projector(condition_id).apply_baseline(
                payload,
                condition_id=condition_id,
                received_at_ms=event.observed_at_ms,
            )
        except MarketDataError as error:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                str(error),
            ) from error

    def _apply_delta(
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

    def _require_delta_generation(
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

    def _required_projector(self, condition_id: str) -> BookDepthProjector:
        projector = self._projectors.get(condition_id)
        if projector is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"book data preceded recorded metadata for {condition_id}",
            )
        return projector

    def _required_market(self, condition_id: str) -> Market:
        market = self._markets_by_condition.get(condition_id)
        if market is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"recorded market metadata is missing for {condition_id}",
            )
        return market


def _market_from_metadata(payload: MarketMetadataPayload) -> Market:
    return Market(
        condition_id=payload.condition_id,
        slug=payload.market_slug,
        question=payload.question,
        minimum_tick_size=payload.minimum_tick_size,
        minimum_order_size=payload.minimum_order_size,
        neg_risk=bool(payload.neg_risk),
        fee_rate=payload.fee_rate,
        outcomes=tuple(
            MarketOutcome(outcome.label, outcome.token_id)
            for outcome in payload.outcomes
        ),
        resolved=payload.resolved,
        winning_token_id=payload.winning_token_id,
        winning_outcome=payload.winning_outcome,
    )
