"""Time-aware market metadata and projected order books for replay."""

from __future__ import annotations

from dataclasses import dataclass, replace

from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.execution.paper.continuity import BookContinuity
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.errors import MarketDataError
from polybot.polymarket.markets import Market, MarketOutcome
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookCheckpoint,
    BookDeltaPayload,
    CoverageGapPayload,
    CoverageGapRecord,
    MarketMetadataPayload,
    PublicTradePayload,
    RecordedEvent,
    ResolutionPayload,
    TickSizeChangePayload,
)
from polybot.recording.coverage import CoverageScope


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
        self._baseline_sequence_by_token: dict[str, int] = {}
        self._bootstrapped_conditions: set[str] = set()
        self._resolved_conditions: set[str] = set()
        self._blackout_conditions: set[str] = set()
        self._continuity_revision_by_condition: dict[str, int] = {}
        self._recovery_after_sequence_by_condition: dict[str, int] = {}
        self._recovery_at_ms_by_condition: dict[str, int] = {}
        self._open_blackout_conditions: set[str] = set()
        self._gap_sequences_by_condition: dict[str, set[int]] = {}
        self._begun_gap_records: dict[int, CoverageGapRecord] = {}

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
        if (
            market is None
            or market.resolved
            or market.condition_id in self._blackout_conditions
        ):
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
        if (
            condition_id in self._resolved_conditions
            or condition_id in self._blackout_conditions
        ):
            return None
        return self._books.get(token_id)

    def book_continuity(self, token_id: str) -> BookContinuity | None:
        condition_id = self._condition_by_token.get(token_id)
        if condition_id is None:
            return None
        return BookContinuity(
            revision=self._continuity_revision_by_condition.get(condition_id, 0),
            blackout=condition_id in self._blackout_conditions,
        )

    def is_blacked_out(self, market_slug: str) -> bool:
        condition_id = self._condition_by_slug.get(market_slug)
        return condition_id in self._blackout_conditions

    def has_bootstrap_evidence(self, market_slug: str) -> bool:
        condition_id = self._condition_by_slug.get(market_slug)
        return condition_id in self._bootstrapped_conditions

    def recover_books_at(self, observed_at_ms: int) -> tuple[BookSnapshot, ...]:
        """Release every complete closed-gap book pair at one time boundary."""
        if (
            isinstance(observed_at_ms, bool)
            or not isinstance(observed_at_ms, int)
            or observed_at_ms < 0
        ):
            raise ValueError("blackout recovery timestamp must be nonnegative")
        staged = tuple(
            (condition_id, snapshots)
            for condition_id in sorted(self._blackout_conditions)
            if (
                snapshots := self._ready_recovery_books(
                    condition_id,
                    observed_at_ms=observed_at_ms,
                )
            )
        )
        recovered: list[BookSnapshot] = []
        for condition_id, snapshots in staged:
            for snapshot in snapshots:
                self._books[snapshot.token_id] = snapshot
            self._bootstrapped_conditions.add(condition_id)
            self._blackout_conditions.remove(condition_id)
            self._recovery_after_sequence_by_condition.pop(condition_id, None)
            self._recovery_at_ms_by_condition.pop(condition_id, None)
            recovered.extend(snapshots)
        return tuple(recovered)

    def add_metadata(self, payload: MarketMetadataPayload) -> Market:
        market = _market_from_metadata(payload)
        previous = self._markets_by_condition.get(market.condition_id)
        if previous is not None and (
            previous.slug != market.slug or previous.token_ids != market.token_ids
        ):
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                "recorded metadata changed immutable identity for "
                f"{market.condition_id}",
            )
        slug_condition = self._condition_by_slug.get(market.slug)
        if slug_condition is not None and slug_condition != market.condition_id:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"market slug maps to multiple recorded markets: {market.slug}",
            )
        for token_id in market.token_ids:
            existing = self._condition_by_token.get(token_id)
            if existing is not None and existing != market.condition_id:
                raise BacktestError(
                    BacktestFailureReason.MISSING_MARKET_DATA,
                    f"token ID maps to multiple recorded markets: {token_id}",
                )
        self._markets_by_condition[market.condition_id] = market
        self._condition_by_slug[market.slug] = market.condition_id
        for token_id in market.token_ids:
            self._condition_by_token[token_id] = market.condition_id
        self._projectors.setdefault(
            market.condition_id,
            BookDepthProjector((market,)),
        )
        if market.resolved:
            self._resolved_conditions.add(market.condition_id)
        else:
            for record in self._begun_gap_records.values():
                if self._gap_affects_market(record, market):
                    self._begin_condition_blackout(market.condition_id, record)
        return market

    def begin_blackout(self, record: CoverageGapRecord) -> tuple[str, ...]:
        if not isinstance(record, CoverageGapRecord):
            raise ValueError("backtest blackout requires a coverage-gap record")
        if record.gap.ended_at_ms == record.gap.started_at_ms:
            return ()
        if record.event_sequence in self._begun_gap_records:
            return ()
        self._begun_gap_records[record.event_sequence] = record
        invalidated: list[str] = []
        for condition_id in sorted(self._conditions_for_gap(record)):
            invalidated.extend(
                self._begin_condition_blackout(condition_id, record)
            )
        return tuple(dict.fromkeys(invalidated))

    def seed_checkpoints(
        self,
        checkpoints: tuple[BookCheckpoint, BookCheckpoint],
    ) -> None:
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
            for _, checkpoint, _ in staged:
                condition_id = checkpoint.identity.condition_id
                if condition_id is not None:
                    self._remember_complete_book(condition_id)
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
            if (
                market is None
                or market.condition_id in self._resolved_conditions
                or market.condition_id in self._blackout_conditions
            ):
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
            if self._ignore_blacked_out_book_event(event, condition_id):
                return AppliedArchiveEvent()
            snapshot = self._apply_baseline(event, payload, condition_id)
            self._generation_by_token[snapshot.token_id] = (
                event.subscription_generation
            )
            self._baseline_sequence_by_token[snapshot.token_id] = event.sequence
            if condition_id in self._blackout_conditions:
                recovered = self.recover_books_at(event.observed_at_ms)
                return AppliedArchiveEvent(books=recovered)
            self._books[snapshot.token_id] = snapshot
            self._remember_complete_book(condition_id)
            return AppliedArchiveEvent(books=(snapshot,))
        if isinstance(payload, BookDeltaPayload):
            if self._ignore_blacked_out_book_event(event, condition_id):
                return AppliedArchiveEvent()
            self._require_delta_generation(event, payload)
            snapshots = self._apply_delta(event, payload, condition_id)
            if condition_id in self._blackout_conditions:
                recovered = self.recover_books_at(event.observed_at_ms)
                return AppliedArchiveEvent(books=recovered)
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
            resolution = MarketResolutionEvent(
                condition_id=condition_id,
                market_slug=market.slug,
                token_ids=payload.token_ids,
                winning_token_id=payload.winning_token_id,
                winning_outcome=payload.winning_outcome,
                resolved_at_ms=event.observed_at_ms,
                source=payload.source,
            )
            updated = replace(
                market,
                resolved=True,
                winning_token_id=payload.winning_token_id,
                winning_outcome=payload.winning_outcome,
            )
            self._markets_by_condition[condition_id] = updated
            self._resolved_conditions.add(condition_id)
            self._blackout_conditions.discard(condition_id)
            return AppliedArchiveEvent(
                resolution=resolution
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

    def _remember_complete_book(self, condition_id: str) -> None:
        market = self._required_market(condition_id)
        if self.has_complete_book(market.slug):
            self._bootstrapped_conditions.add(condition_id)

    def _conditions_for_gap(self, record: CoverageGapRecord) -> set[str]:
        scope = CoverageScope.from_gap(record.gap, record.identity)
        if scope.is_global:
            return set(self._markets_by_condition)
        condition_ids = set(scope.condition_ids)
        condition_ids.update(
            condition_id
            for slug in scope.market_slugs
            if (condition_id := self._condition_by_slug.get(slug)) is not None
        )
        condition_ids.update(
            condition_id
            for token_id in scope.token_ids
            if (condition_id := self._condition_by_token.get(token_id)) is not None
        )
        return condition_ids

    def _gap_affects_market(
        self,
        record: CoverageGapRecord,
        market: Market,
    ) -> bool:
        scope = CoverageScope.from_gap(record.gap, record.identity)
        return scope.is_global or bool(
            market.condition_id in scope.condition_ids
            or market.slug in scope.market_slugs
            or not set(market.token_ids).isdisjoint(scope.token_ids)
        )

    def _begin_condition_blackout(
        self,
        condition_id: str,
        record: CoverageGapRecord,
    ) -> tuple[str, ...]:
        gap_sequences = self._gap_sequences_by_condition.setdefault(
            condition_id,
            set(),
        )
        if record.event_sequence in gap_sequences:
            return ()
        gap_sequences.add(record.event_sequence)
        if condition_id in self._resolved_conditions:
            return ()

        self._blackout_conditions.add(condition_id)
        self._continuity_revision_by_condition[condition_id] = (
            self._continuity_revision_by_condition.get(condition_id, 0) + 1
        )
        self._recovery_after_sequence_by_condition[condition_id] = max(
            record.event_sequence,
            self._recovery_after_sequence_by_condition.get(condition_id, 0),
        )
        if record.gap.ended_at_ms is None:
            self._open_blackout_conditions.add(condition_id)
        else:
            self._recovery_at_ms_by_condition[condition_id] = max(
                record.gap.ended_at_ms,
                self._recovery_at_ms_by_condition.get(condition_id, 0),
            )

        projector = self._projectors.get(condition_id)
        if projector is not None:
            projector.clear()
        market = self._markets_by_condition.get(condition_id)
        if market is None:
            return ()
        for token_id in market.token_ids:
            self._books.pop(token_id, None)
            self._generation_by_token.pop(token_id, None)
            self._baseline_sequence_by_token.pop(token_id, None)
        return market.token_ids

    def _ignore_blacked_out_book_event(
        self,
        event: RecordedEvent,
        condition_id: str,
    ) -> bool:
        if condition_id not in self._blackout_conditions:
            return False
        recovery_after_sequence = self._recovery_after_sequence_by_condition.get(
            condition_id,
            0,
        )
        if event.sequence <= recovery_after_sequence:
            return True
        payload = event.payload
        if not isinstance(payload, BookDeltaPayload):
            return False
        return any(
            self._baseline_sequence_by_token.get(change.token_id, 0)
            <= recovery_after_sequence
            or self._generation_by_token.get(change.token_id)
            != event.subscription_generation
            for change in payload.changes
        )

    def _ready_recovery_books(
        self,
        condition_id: str,
        *,
        observed_at_ms: int,
    ) -> tuple[BookSnapshot, ...]:
        if condition_id not in self._blackout_conditions:
            return ()
        if condition_id in self._open_blackout_conditions:
            return ()
        if observed_at_ms < self._recovery_at_ms_by_condition.get(
            condition_id,
            0,
        ):
            return ()
        market = self._required_market(condition_id)
        recovery_after_sequence = self._recovery_after_sequence_by_condition.get(
            condition_id,
            0,
        )
        if any(
            self._baseline_sequence_by_token.get(token_id, 0)
            <= recovery_after_sequence
            for token_id in market.token_ids
        ):
            return ()
        generations = {
            self._generation_by_token.get(token_id)
            for token_id in market.token_ids
        }
        if None in generations or len(generations) != 1:
            return ()
        projector = self._required_projector(condition_id)
        if not set(market.token_ids).issubset(projector.baseline_token_ids):
            return ()
        snapshots_by_token = {
            snapshot.token_id: snapshot
            for snapshot in projector.snapshots(
                received_at_ms=observed_at_ms,
            )
        }
        if not set(market.token_ids).issubset(snapshots_by_token):
            return ()
        snapshots = tuple(
            snapshots_by_token[token_id] for token_id in market.token_ids
        )
        return snapshots


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
