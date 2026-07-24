"""Coverage-gap blackout and atomic book-recovery state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from polybot.execution.paper.continuity import BookContinuity
from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.markets import Market
from polybot.recording.contracts.book import BookDeltaPayload
from polybot.recording.contracts.records import CoverageGapRecord, RecordedEvent
from polybot.recording.coverage import CoverageScope

if TYPE_CHECKING:
    from .books import ProjectedBookReplay
    from .catalog import MarketCatalog


class CoverageBlackouts:
    """Own blackout scope, continuity revisions, and recovery boundaries."""

    def __init__(self) -> None:
        self._blackout_conditions: set[str] = set()
        self._continuity_revision_by_condition: dict[str, int] = {}
        self._recovery_after_sequence_by_condition: dict[str, int] = {}
        self._recovery_at_ms_by_condition: dict[str, int] = {}
        self._open_blackout_conditions: set[str] = set()
        self._gap_sequences_by_condition: dict[str, set[int]] = {}
        self._begun_gap_records: dict[int, CoverageGapRecord] = {}

    def is_blacked_out(self, condition_id: str | None) -> bool:
        return condition_id in self._blackout_conditions

    def continuity(self, condition_id: str) -> BookContinuity:
        return BookContinuity(
            revision=self._continuity_revision_by_condition.get(condition_id, 0),
            blackout=condition_id in self._blackout_conditions,
        )

    def begin(
        self,
        record: CoverageGapRecord,
        catalog: MarketCatalog,
        books: ProjectedBookReplay,
    ) -> tuple[str, ...]:
        if not isinstance(record, CoverageGapRecord):
            raise ValueError("backtest blackout requires a coverage-gap record")
        if record.gap.is_instantaneous:
            return ()
        if record.event_sequence in self._begun_gap_records:
            return ()
        self._begun_gap_records[record.event_sequence] = record
        invalidated: list[str] = []
        for condition_id in sorted(self._conditions_for_gap(record, catalog)):
            invalidated.extend(
                self._begin_condition(
                    condition_id,
                    record,
                    catalog,
                    books,
                )
            )
        return tuple(dict.fromkeys(invalidated))

    def apply_pending_to_market(
        self,
        market: Market,
        catalog: MarketCatalog,
        books: ProjectedBookReplay,
    ) -> None:
        for record in self._begun_gap_records.values():
            if self._gap_affects_market(record, market):
                self._begin_condition(
                    market.condition_id,
                    record,
                    catalog,
                    books,
                )

    def should_ignore_book_event(
        self,
        event: RecordedEvent,
        condition_id: str,
        books: ProjectedBookReplay,
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
            books.baseline_sequence(change.token_id) <= recovery_after_sequence
            or books.generation(change.token_id) != event.subscription_generation
            for change in payload.changes
        )

    def recover_books_at(
        self,
        observed_at_ms: int,
        catalog: MarketCatalog,
        books: ProjectedBookReplay,
    ) -> tuple[BookSnapshot, ...]:
        _validate_recovery_timestamp(observed_at_ms)
        staged = tuple(
            (condition_id, snapshots)
            for condition_id in sorted(self._blackout_conditions)
            if (
                snapshots := self._ready_recovery_books(
                    condition_id,
                    observed_at_ms=observed_at_ms,
                    catalog=catalog,
                    books=books,
                )
            )
        )
        recovered: list[BookSnapshot] = []
        for condition_id, snapshots in staged:
            books.publish_many(snapshots)
            books.mark_bootstrapped(condition_id)
            self._blackout_conditions.remove(condition_id)
            self._recovery_after_sequence_by_condition.pop(condition_id, None)
            self._recovery_at_ms_by_condition.pop(condition_id, None)
            recovered.extend(snapshots)
        return tuple(recovered)

    def clear_on_resolution(self, condition_id: str) -> None:
        self._blackout_conditions.discard(condition_id)

    def _conditions_for_gap(
        self,
        record: CoverageGapRecord,
        catalog: MarketCatalog,
    ) -> set[str]:
        scope = CoverageScope.from_gap(record.gap, record.identity)
        if scope.is_global:
            return {market.condition_id for market in catalog.markets}
        condition_ids = set(scope.condition_ids)
        condition_ids.update(
            condition_id
            for slug in scope.market_slugs
            if (condition_id := catalog.condition_for_slug(slug)) is not None
        )
        condition_ids.update(
            condition_id
            for token_id in scope.token_ids
            if (condition_id := catalog.condition_for_token(token_id)) is not None
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

    def _begin_condition(
        self,
        condition_id: str,
        record: CoverageGapRecord,
        catalog: MarketCatalog,
        books: ProjectedBookReplay,
    ) -> tuple[str, ...]:
        gap_sequences = self._gap_sequences_by_condition.setdefault(
            condition_id,
            set(),
        )
        if record.event_sequence in gap_sequences:
            return ()
        gap_sequences.add(record.event_sequence)
        if catalog.is_resolved(condition_id):
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

        market = catalog.market_for_condition(condition_id)
        return () if market is None else books.clear_condition(market)

    def _ready_recovery_books(
        self,
        condition_id: str,
        *,
        observed_at_ms: int,
        catalog: MarketCatalog,
        books: ProjectedBookReplay,
    ) -> tuple[BookSnapshot, ...]:
        if condition_id in self._open_blackout_conditions:
            return ()
        if observed_at_ms < self._recovery_at_ms_by_condition.get(condition_id, 0):
            return ()
        market = catalog.require_market(condition_id)
        return books.recovery_snapshots(
            market,
            recovery_after_sequence=self._recovery_after_sequence_by_condition.get(
                condition_id,
                0,
            ),
            observed_at_ms=observed_at_ms,
        )


def _validate_recovery_timestamp(observed_at_ms: int) -> None:
    if (
        isinstance(observed_at_ms, bool)
        or not isinstance(observed_at_ms, int)
        or observed_at_ms < 0
    ):
        raise ValueError("blackout recovery timestamp must be nonnegative")
