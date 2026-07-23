"""Archive replay coordinator for normalized markets, books, and blackouts."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.execution.paper.continuity import BookContinuity
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.markets import Market
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
    TickSizeChangePayload,
)
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)
from polybot.recording.contracts.records import (
    BookCheckpoint,
    CoverageGapRecord,
    RecordedEvent,
)

from .blackouts import CoverageBlackouts
from .books import ProjectedBookReplay
from .catalog import MarketCatalog


@dataclass(frozen=True, slots=True)
class AppliedArchiveEvent:
    books: tuple[BookSnapshot, ...] = ()
    resolution: MarketResolutionEvent | None = None


class ArchiveMarketState:
    """Coordinate durable market indexes, book projection, and gap recovery."""

    def __init__(self) -> None:
        self._catalog = MarketCatalog()
        self._book_replay = ProjectedBookReplay()
        self._blackouts = CoverageBlackouts()

    @property
    def markets(self) -> tuple[Market, ...]:
        return self._catalog.markets

    @property
    def market_slugs(self) -> frozenset[str]:
        return self._catalog.market_slugs

    @property
    def books(self) -> dict[str, BookSnapshot]:
        return self._book_replay.books

    def has_complete_book(self, market_slug: str) -> bool:
        market = self.market_for_slug(market_slug)
        return bool(
            market is not None
            and not market.resolved
            and not self._blackouts.is_blacked_out(market.condition_id)
            and self._book_replay.has_complete_book(market)
        )

    def market_for_slug(self, slug: str) -> Market | None:
        return self._catalog.market_for_slug(slug)

    async def find_by_slug(self, slug: str) -> Market | None:
        return self.market_for_slug(slug)

    async def latest(self, token_id: str) -> BookSnapshot | None:
        condition_id = self._catalog.condition_for_token(token_id)
        if self._catalog.is_resolved(condition_id) or self._blackouts.is_blacked_out(
            condition_id
        ):
            return None
        return self._book_replay.latest(token_id)

    def book_continuity(self, token_id: str) -> BookContinuity | None:
        condition_id = self._catalog.condition_for_token(token_id)
        return (
            None if condition_id is None else self._blackouts.continuity(condition_id)
        )

    def is_blacked_out(self, market_slug: str) -> bool:
        return self._blackouts.is_blacked_out(
            self._catalog.condition_for_slug(market_slug)
        )

    def has_bootstrap_evidence(self, market_slug: str) -> bool:
        return self._book_replay.has_bootstrap_evidence(
            self._catalog.condition_for_slug(market_slug)
        )

    def recover_books_at(self, observed_at_ms: int) -> tuple[BookSnapshot, ...]:
        """Release every complete closed-gap book pair at one time boundary."""
        return self._blackouts.recover_books_at(
            observed_at_ms,
            self._catalog,
            self._book_replay,
        )

    def add_metadata(self, payload: MarketMetadataPayload) -> Market:
        market = self._catalog.add_metadata(payload)
        self._book_replay.register_market(market)
        if not market.resolved:
            self._blackouts.apply_pending_to_market(
                market,
                self._catalog,
                self._book_replay,
            )
        return market

    def begin_blackout(self, record: CoverageGapRecord) -> tuple[str, ...]:
        return self._blackouts.begin(record, self._catalog, self._book_replay)

    def seed_checkpoints(
        self,
        checkpoints: tuple[BookCheckpoint, BookCheckpoint],
    ) -> None:
        for condition_id in self._book_replay.seed_checkpoints(checkpoints):
            self._remember_complete_book(condition_id)

    def bootstrap_books(
        self,
        market_slugs: set[str] | frozenset[str],
        *,
        received_at_ms: int,
    ) -> tuple[BookSnapshot, ...]:
        markets = tuple(
            market
            for slug in sorted(market_slugs)
            if (market := self.market_for_slug(slug)) is not None
            and not self._catalog.is_resolved(market.condition_id)
            and not self._blackouts.is_blacked_out(market.condition_id)
        )
        return self._book_replay.bootstrap_books(
            markets,
            received_at_ms=received_at_ms,
        )

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
        condition_id = None if event.identity is None else event.identity.condition_id
        if condition_id is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"recorded event {event.sequence} has no condition identity",
            )
        if isinstance(payload, BookBaselinePayload):
            if self._blackouts.should_ignore_book_event(
                event,
                condition_id,
                self._book_replay,
            ):
                return AppliedArchiveEvent()
            snapshot = self._book_replay.apply_baseline(
                event,
                payload,
                condition_id,
            )
            if self._blackouts.is_blacked_out(condition_id):
                return AppliedArchiveEvent(
                    books=self.recover_books_at(event.observed_at_ms)
                )
            self._book_replay.publish(snapshot)
            self._remember_complete_book(condition_id)
            return AppliedArchiveEvent(books=(snapshot,))
        if isinstance(payload, BookDeltaPayload):
            if self._blackouts.should_ignore_book_event(
                event,
                condition_id,
                self._book_replay,
            ):
                return AppliedArchiveEvent()
            self._book_replay.require_delta_generation(event, payload)
            snapshots = self._book_replay.apply_delta(event, payload, condition_id)
            if self._blackouts.is_blacked_out(condition_id):
                return AppliedArchiveEvent(
                    books=self.recover_books_at(event.observed_at_ms)
                )
            self._book_replay.publish_many(snapshots)
            return AppliedArchiveEvent(books=snapshots)
        if isinstance(payload, TickSizeChangePayload):
            self._catalog.update_tick_size(condition_id, payload.new_tick_size)
            return AppliedArchiveEvent()
        if isinstance(payload, PublicTradePayload):
            return AppliedArchiveEvent()
        if isinstance(payload, ResolutionPayload):
            market = self._catalog.require_market(condition_id)
            resolution = MarketResolutionEvent(
                condition_id=condition_id,
                market_slug=market.slug,
                token_ids=payload.token_ids,
                winning_token_id=payload.winning_token_id,
                winning_outcome=payload.winning_outcome,
                resolved_at_ms=event.observed_at_ms,
                source=payload.source,
            )
            self._catalog.resolve(condition_id, payload)
            self._blackouts.clear_on_resolution(condition_id)
            return AppliedArchiveEvent(resolution=resolution)
        raise TypeError(f"unsupported recorded payload: {type(payload).__name__}")

    def _remember_complete_book(self, condition_id: str) -> None:
        market = self._catalog.require_market(condition_id)
        if self.has_complete_book(market.slug):
            self._book_replay.mark_bootstrapped(condition_id)
