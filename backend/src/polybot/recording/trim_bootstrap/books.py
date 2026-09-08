from __future__ import annotations

from dataclasses import dataclass

from polybot.backtesting.state import ArchiveMarketState
from polybot.recording.contracts.book import BookBaselinePayload
from polybot.recording.contracts.market import MarketIdentity, MarketMetadataPayload
from polybot.recording.contracts.records import BookCheckpoint, RecordedEvent
from polybot.recording.serialization.registry import payload_kind


@dataclass(frozen=True, slots=True)
class BootstrapBook:
    identity: MarketIdentity
    generation: int
    book: BookBaselinePayload

    def matches_checkpoint(
        self,
        checkpoint_by_token: dict[str, BookCheckpoint],
    ) -> bool:
        checkpoint = checkpoint_by_token.get(self.book.token_id)
        return (
            checkpoint is not None
            and checkpoint.subscription_generation == self.generation
            and checkpoint.book == self.book
        )


@dataclass(frozen=True, slots=True)
class BootstrapState:
    metadata: MarketMetadataPayload
    books: tuple[BootstrapBook, ...]


def is_checkpoint_state_event(event: RecordedEvent) -> bool:
    return payload_kind(event.payload).affects_book_state


def bootstrap_books(
    state: ArchiveMarketState,
    market: MarketMetadataPayload,
    generation_by_token: dict[str, int],
) -> tuple[BootstrapBook, ...]:
    books = state.books
    result: list[BootstrapBook] = []
    for outcome in market.outcomes:
        snapshot = books.get(outcome.token_id)
        generation = generation_by_token.get(outcome.token_id)
        if snapshot is None or generation is None:
            continue
        result.append(
            BootstrapBook(
                identity=MarketIdentity(
                    condition_id=market.condition_id,
                    market_slug=market.market_slug,
                    token_id=outcome.token_id,
                ),
                generation=generation,
                book=BookBaselinePayload.from_snapshot(snapshot),
            )
        )
    return tuple(result)
