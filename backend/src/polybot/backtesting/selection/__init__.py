from __future__ import annotations

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestOptions,
    BacktestSelection,
)
from polybot.backtesting.selection.bootstrap import ReplayBootstrap
from polybot.recording.archive.models import RecordingSession
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.session import SessionIntegrityStatus


class ReplaySelectionResolver:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def resolve(
        self,
        session: RecordingSession,
        options: BacktestOptions,
    ) -> BacktestSelection:
        """Resolve and gap-check one requested session, range, and market set."""

        allow_gaps = options.gap_policy.allows_gaps

        effective_end_at_ms = self.session_end(session)
        if effective_end_at_ms is None:
            raise BacktestError(
                BacktestFailureReason.SESSION_NOT_REPLAYABLE,
                f"recording session {session.session_id} is not cleanly replayable",
            )
        requested_start = (
            session.started_at_ms
            if options.start_at_ms is None
            else options.start_at_ms
        )
        requested_end = (
            effective_end_at_ms if options.end_at_ms is None else options.end_at_ms
        )
        if (
            requested_start < session.started_at_ms
            or requested_end > effective_end_at_ms
            or requested_end < requested_start
        ):
            raise BacktestError(
                BacktestFailureReason.INVALID_SELECTION,
                "backtest range must lie inside the selected recording session",
            )
        available_markets = self._reader.markets_at(
            requested_end,
            session_id=session.session_id,
            allow_gaps=True,
        )
        available_slugs = tuple(
            sorted({market.market_slug for market in available_markets})
        )
        if options.market_slugs:
            selected_slugs = options.market_slugs
        elif options.start_at_ms is not None:
            selected_slugs = available_slugs
        else:
            selected_slugs = self.default_replayable_slugs(
                available_markets,
                start_at_ms=requested_start,
                end_at_ms=requested_end,
                session_id=session.session_id,
            )
        missing = sorted(set(selected_slugs).difference(available_slugs))
        if missing:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                "selected markets are absent from the recording session: "
                + ", ".join(missing),
            )
        if not selected_slugs:
            raise BacktestError(
                BacktestFailureReason.EMPTY_SELECTION,
                "selected recording session contains no market data",
            )
        bounds = self._reader.event_bounds(
            start_at_ms=requested_start,
            end_at_ms=requested_end,
            session_id=session.session_id,
            market_slugs=selected_slugs,
            allow_gaps=allow_gaps,
        )
        if bounds is None:
            raise BacktestError(
                BacktestFailureReason.EMPTY_SELECTION,
                "selected recording range contains no events",
            )
        start_at_ms = (
            bounds.start_at_ms if options.start_at_ms is None else requested_start
        )
        return BacktestSelection(
            session_id=session.session_id,
            start_at_ms=start_at_ms,
            end_at_ms=requested_end,
            market_slugs=tuple(selected_slugs),
            replay_cutoff_sequence=self._reader.replay_cutoff_sequence,
            session_integrity_status=session.integrity_status,
            uses_partial_session=(
                session.integrity_status is not SessionIntegrityStatus.COMPLETE
            ),
            gap_policy=options.gap_policy,
        )

    def default_replayable_slugs(
        self,
        markets: tuple[MarketMetadataPayload, ...],
        *,
        start_at_ms: int,
        end_at_ms: int,
        session_id: int,
    ) -> tuple[str, ...]:
        """Skip metadata-only rollover candidates in the default selection.

        Dynamic recorders can persist metadata and a terminal lifecycle event for
        a future bucket before its first full books arrive.  Those candidates are
        valid recorder observations but are not replayable markets.  Explicit
        ``--market-slug`` selection remains strict and still reports the missing
        bootstrap as an error.
        """

        replayable: list[str] = []
        for market in markets:
            if self._reader.has_complete_baseline_pair(
                market,
                start_at_ms=start_at_ms,
                end_at_ms=end_at_ms,
                session_id=session_id,
            ):
                replayable.append(market.market_slug)
                continue
            if (
                ReplayBootstrap(self._reader).checkpoint_pair(
                    condition_id=market.condition_id,
                    start_at_ms=start_at_ms,
                    session_id=session_id,
                    allow_pre_gap_checkpoint=False,
                )
                is not None
            ):
                replayable.append(market.market_slug)
                continue
            # Preserve fail-closed validation for markets that did record book
            # input but cannot reconstruct a pair.  A metadata-only rollover
            # candidate has only its metadata and terminal lifecycle records.
            if (
                self._reader.event_count(
                    start_at_ms=start_at_ms,
                    end_at_ms=end_at_ms,
                    session_id=session_id,
                    market_slug=market.market_slug,
                    allow_gaps=True,
                )
                > 2
            ):
                replayable.append(market.market_slug)
        return tuple(sorted(replayable))

    def session_end(
        self,
        session: RecordingSession,
    ) -> int | None:
        """Return the replayable session boundary, including a durable partial end."""

        if session.integrity_status is SessionIntegrityStatus.ACTIVE:
            return None
        if (
            session.integrity_status is SessionIntegrityStatus.COMPLETE
            and not session.clean_close
        ):
            return None
        if session.clean_close:
            return session.ended_at_ms
        if session.integrity_status not in {
            SessionIntegrityStatus.INCOMPLETE,
            SessionIntegrityStatus.FAILED,
        }:
            return None
        durable_end_at_ms = self._reader.session_durable_end_at_ms(session.session_id)
        if durable_end_at_ms is None:
            return None
        if session.ended_at_ms is None:
            return durable_end_at_ms
        return min(session.ended_at_ms, durable_end_at_ms)
