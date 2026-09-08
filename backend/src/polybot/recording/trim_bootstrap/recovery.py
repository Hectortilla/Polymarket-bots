from __future__ import annotations

from dataclasses import replace

from polybot.backtesting.state import ArchiveMarketState
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.book import BookBaselinePayload, BookDeltaPayload
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.records import BookCheckpoint
from polybot.recording.trim_bootstrap.books import (
    BootstrapState,
    bootstrap_books,
    is_checkpoint_state_event,
)
from polybot.recording.trim_contracts import RecordingTrimError, RecordingTrimPlan
from polybot.recording.trim_recovery.boundaries import RecoveryTokenBoundary


class RecoveryBootstrap:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def state_at_checkpoint(
        self,
        plan: RecordingTrimPlan,
        market: MarketMetadataPayload,
        checkpoints: tuple[BookCheckpoint, BookCheckpoint],
        *,
        scan_boundaries: tuple[RecoveryTokenBoundary, ...],
    ) -> BootstrapState:
        boundary_sequence = checkpoints[0].sequence
        materialized_metadata = self._reader.market_state_at(
            market.condition_id,
            plan.start_at_ms,
            sequence_cutoff=boundary_sequence,
            allow_gaps=True,
        )
        if materialized_metadata is None:
            raise RecordingTrimError(
                "recovery checkpoint has no preceding market metadata: "
                f"{market.market_slug}"
            )
        state = ArchiveMarketState()
        state.add_metadata(materialized_metadata)
        generation_by_token: dict[str, int] = {}
        sequence_cutoff_by_token = {
            boundary.token_id: boundary.after_sequence for boundary in scan_boundaries
        }
        for event in self._reader.iter_events(
            start_at_ms=min(boundary.start_at_ms for boundary in scan_boundaries),
            end_at_ms=plan.start_at_ms,
            session_id=plan.source_session.session_id,
            condition_id=market.condition_id,
            allow_gaps=True,
        ):
            if event.sequence > boundary_sequence:
                if (
                    event.observed_at_ms < plan.start_at_ms
                    and is_checkpoint_state_event(event)
                ):
                    raise RecordingTrimError(
                        "recovery checkpoint precedes canonical book state at its "
                        f"observation: {market.market_slug}"
                    )
                continue
            if isinstance(event.payload, BookBaselinePayload):
                token_id = event.payload.token_id
                if event.sequence <= sequence_cutoff_by_token[token_id]:
                    continue
                state.apply(event)
                generation_by_token[token_id] = event.subscription_generation
                continue
            if isinstance(event.payload, BookDeltaPayload):
                changes = tuple(
                    change
                    for change in event.payload.changes
                    if event.sequence > sequence_cutoff_by_token[change.token_id]
                )
                if not changes:
                    continue
                state.apply(
                    event
                    if changes == event.payload.changes
                    else replace(
                        event,
                        payload=BookDeltaPayload(changes=changes),
                    )
                )

        books = bootstrap_books(state, market, generation_by_token)
        checkpoint_by_token = {
            checkpoint.book.token_id: checkpoint for checkpoint in checkpoints
        }
        if len(books) != len(market.outcomes) or not all(
            book.matches_checkpoint(checkpoint_by_token) for book in books
        ):
            raise RecordingTrimError(
                "recovery checkpoint does not match canonical book baselines: "
                f"{market.market_slug}"
            )
        return BootstrapState(materialized_metadata, books)
