"""Paper-position book refreshes for dashboard valuation."""

from __future__ import annotations

from collections.abc import Mapping
from time import monotonic
from typing import Protocol

from polybot.cli.observability.events import PortfolioBookBootstrap
from polybot.cli.observability.observer import (
    RuntimeObserver,
    emit_observer_fail_open,
)
from polybot.framework.events.books import BookSnapshot


class PaperPortfolioWithPositions(Protocol):
    positions: Mapping[str, object]


class PaperBrokerWithPositions(Protocol):
    @property
    def portfolio(self) -> PaperPortfolioWithPositions: ...


class PositionBookClient(Protocol):
    async def latest(self, token_id: str) -> BookSnapshot | None: ...


async def emit_paper_position_book_bootstraps(
    paper_broker: PaperBrokerWithPositions,
    client: PositionBookClient,
    observer: RuntimeObserver,
) -> None:
    """Refresh dashboard marks while a replacement subscription establishes."""

    try:
        positions = paper_broker.portfolio.positions
    except AttributeError:
        return
    for token_id in sorted(positions):
        try:
            book = await client.latest(token_id)
        except Exception:
            continue
        if book is not None and book.has_valid_levels() and not book.is_crossed():
            emit_observer_fail_open(
                observer,
                PortfolioBookBootstrap(book, monotonic()),
            )
