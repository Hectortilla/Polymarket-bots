from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager

from polybot.framework.clock import system_now_ms
from polybot.framework.events.books import BookGapEvent, BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.client_lifecycle import (
    PublicClientLease,
)
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
    MarketDataTransportError,
)
from polybot.polymarket.market_hints import MarketTradeHint
from polybot.polymarket.markets import (
    Market,
    index_markets_by_token,
)
from polybot.polymarket.normalization.recording_events import normalize_recording_event
from polybot.polymarket.stream_diagnostics import (
    require_monotonic_dropped_count,
    sdk_dropped_count,
)
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
)
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)

from polymarket import AsyncPublicClient, PolymarketError
from polymarket.streams import MarketSpec

from .book_gaps import MarketBookGaps
from .market_routing import _market_for_event


class MarketStream:
    def __init__(
        self,
        client: AsyncPublicClient | None = None,
        *,
        markets: Iterable[Market] = (),
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client_lease = PublicClientLease.acquire(client)
        self._client = self._client_lease.client
        self._now_ms = now_ms or system_now_ms
        self._market_by_token: dict[str, Market] = {}
        self._market_by_condition: dict[str, Market] = {}
        self._gaps = MarketBookGaps(self._now_ms)
        self.set_markets(markets)

    @property
    def last_book_gap(self) -> BookGapEvent | None:
        """Return the most recent typed reason a book baseline was invalidated."""
        return self._gaps.last

    @property
    def book_gap_count(self) -> int:
        """Return the number of book continuity losses for this adapter."""
        return self._gaps.count

    def set_markets(self, markets: Iterable[Market]) -> None:
        normalized = tuple(markets)
        self._market_by_token = index_markets_by_token(normalized)
        self._market_by_condition = {
            market.condition_id: market for market in normalized
        }

    async def books(
        self,
        token_ids: set[str],
    ) -> AsyncIterator[BookSnapshot | BookGapEvent]:
        async for event in self.events(token_ids):
            if isinstance(event, (BookSnapshot, BookGapEvent)):
                yield event

    async def events(
        self,
        token_ids: set[str],
    ) -> AsyncIterator[
        BookSnapshot | BookGapEvent | MarketTradeHint | MarketResolutionEvent
    ]:
        normalized_token_ids = frozenset(token_id for token_id in token_ids if token_id)
        if len(normalized_token_ids) != len(token_ids) or not normalized_token_ids:
            raise MarketDataError(
                MarketDataIssue.EMPTY_IDENTIFIER,
                "at least one non-empty token ID is required",
            )

        # A subscription is one immutable market generation.  The runner may
        # replace the next generation while an SDK event from this one is
        # still being delivered; keep identity normalization tied to this
        # generation instead of observing the mutable adapter-wide registry.
        market_by_token = self._market_by_token.copy()
        market_by_condition = self._market_by_condition.copy()
        projector = BookDepthProjector(market_by_condition.values())
        recovering_conditions: set[str] = set()
        try:
            stream = await self._client.subscribe(
                MarketSpec(
                    token_ids=tuple(sorted(normalized_token_ids)),
                    custom_feature_enabled=True,
                ),
            )
        except PolymarketError as error:
            raise MarketDataTransportError(
                "market stream subscription failed"
            ) from error
        dropped_count = sdk_dropped_count(stream)
        async with _normalized_subscription(stream) as subscribed_events:
            async for event in subscribed_events:
                current_dropped_count = require_monotonic_dropped_count(
                    dropped_count,
                    sdk_dropped_count(stream),
                )
                if current_dropped_count > dropped_count:
                    projector.clear()
                    recovering_conditions.update(market_by_condition)
                    yield self._gaps.record(
                        MarketDataIssue.BOOK_STREAM_GAP,
                        condition_id=None,
                        observed_at_ms=self._now_ms(),
                    )
                dropped_count = current_dropped_count
                try:
                    market = _market_for_event(
                        event,
                        subscribed_token_ids=normalized_token_ids,
                        market_by_token=market_by_token,
                        market_by_condition=market_by_condition,
                    )
                    if market is None:
                        gap = self._gaps.invalidate_unrouteable(projector, event)
                        if gap is not None:
                            recovering_conditions.update(market_by_condition)
                            yield gap
                        continue
                except (AttributeError, MarketDataError, ValueError) as error:
                    gap = self._gaps.invalidate_unrouteable(
                        projector,
                        event,
                        issue=_market_data_issue(error),
                    )
                    if gap is not None:
                        recovering_conditions.update(market_by_condition)
                        yield gap
                    continue
                try:
                    captured = normalize_recording_event(event, market=market)
                except (AttributeError, MarketDataError, ValueError) as error:
                    gap = self._gaps.invalidate_rejected(
                        projector,
                        event,
                        market,
                        issue=_market_data_issue(error),
                    )
                    if gap is not None:
                        recovering_conditions.add(market.condition_id)
                        yield gap
                    continue
                if captured is None:
                    continue

                condition_id = captured.identity.condition_id
                if condition_id is None:
                    continue
                observed_at_ms = self._now_ms()
                if isinstance(captured.payload, BookBaselinePayload):
                    try:
                        snapshot = projector.apply_baseline(
                            captured.payload,
                            condition_id=condition_id,
                            received_at_ms=observed_at_ms,
                        )
                    except MarketDataError as error:
                        gap = self._gaps.invalidate_rejected(
                            projector,
                            event,
                            market,
                            issue=error.issue,
                            observed_at_ms=observed_at_ms,
                        )
                        if gap is not None:
                            recovering_conditions.add(market.condition_id)
                            yield gap
                        continue
                    if condition_id not in recovering_conditions:
                        yield snapshot
                    elif projector.has_baselines(
                        token_id
                        for token_id in market.token_ids
                        if token_id in normalized_token_ids
                    ):
                        for recovered_snapshot in projector.condition_snapshots(
                            condition_id,
                            received_at_ms=observed_at_ms,
                        ):
                            yield recovered_snapshot
                        recovering_conditions.remove(condition_id)
                elif isinstance(captured.payload, BookDeltaPayload):
                    changes = tuple(
                        change
                        for change in captured.payload.changes
                        if change.token_id in normalized_token_ids
                        and change.token_id in projector.baseline_token_ids
                    )
                    if not changes:
                        continue
                    try:
                        snapshots = projector.apply_delta(
                            BookDeltaPayload(changes=changes),
                            condition_id=condition_id,
                            received_at_ms=observed_at_ms,
                        )
                    except MarketDataError as error:
                        gap = self._gaps.invalidate_rejected(
                            projector,
                            event,
                            market,
                            issue=error.issue,
                            observed_at_ms=observed_at_ms,
                        )
                        if gap is not None:
                            recovering_conditions.add(market.condition_id)
                            yield gap
                        continue
                    if condition_id in recovering_conditions:
                        continue
                    for snapshot in snapshots:
                        yield snapshot
                elif isinstance(captured.payload, PublicTradePayload):
                    yield MarketTradeHint(
                        condition_id,
                        captured.payload.token_id,
                        market.slug,
                        observed_at_ms,
                    )
                elif isinstance(captured.payload, ResolutionPayload):
                    yield MarketResolutionEvent(
                        condition_id=condition_id,
                        market_slug=market.slug,
                        token_ids=market.token_ids,
                        winning_token_id=captured.payload.winning_token_id,
                        winning_outcome=captured.payload.winning_outcome,
                        resolved_at_ms=(
                            captured.source_timestamp_ms
                            if captured.source_timestamp_ms is not None
                            else observed_at_ms
                        ),
                        source=captured.payload.source,
                    )

    async def close(self) -> None:
        await self._client_lease.close()


@asynccontextmanager
async def _normalized_subscription(stream: object) -> AsyncIterator[object]:
    """Normalize SDK stream lifecycle failures at the adapter boundary."""
    try:
        async with stream:  # type: ignore[attr-defined]
            yield stream
    except PolymarketError as error:
        raise MarketDataTransportError("market stream failed") from error


def _market_data_issue(error: BaseException) -> MarketDataIssue:
    if isinstance(error, MarketDataError):
        return error.issue
    return MarketDataIssue.INVALID_MARKET_PARAMETERS
