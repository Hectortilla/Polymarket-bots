"""Construction and lifecycle of one deterministic archive replay."""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from pathlib import Path

from polybot.backtesting.broker import BacktestPerformanceBroker
from polybot.backtesting.clients import (
    RejectingPositionClient,
    RejectingPlanningBroker,
    RejectingWalletActivityClient,
)
from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestOptions,
    BacktestResult,
    BacktestSelection,
)
from polybot.backtesting.scheduler import ReplayCursor, ReplayScheduler
from polybot.backtesting.state import ArchiveMarketState
from polybot.execution.paper import PaperBroker
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig, BotMode
from polybot.framework.context import BotContext
from polybot.framework.runner import BotRunner
from polybot.performance.artifacts import PerformanceArtifacts
from polybot.performance.contracts import (
    PerformanceRunKind,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
)
from polybot.recording.archive import (
    ArchiveCoverageError,
    ArchiveFormatError,
    ArchiveIntegrityError,
    ArchiveLockedError,
    RecordingArchiveError,
    RecordingReader,
    RecordingSession,
)
from polybot.recording.contracts import (
    BookBaselinePayload,
    MarketMetadataPayload,
    RecordedEvent,
    SessionIntegrityStatus,
)


async def run_backtest(
    bot: BaseBot,
    config: BotConfig,
    *,
    bot_spec: str,
    options: BacktestOptions,
) -> BacktestResult:
    if config.mode is BotMode.LIVE:
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            "backtesting cannot run with BOT_MODE=live",
        )
    try:
        reader = RecordingReader.for_replay(options.archive_path)
    except ArchiveLockedError as error:
        raise BacktestError(
            BacktestFailureReason.SESSION_NOT_REPLAYABLE,
            str(error),
        ) from error
    except ArchiveFormatError as error:
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_ARCHIVE,
            str(error),
        ) from error
    except RecordingArchiveError as error:
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_ARCHIVE,
            str(error),
        ) from error

    with reader:
        try:
            session = reader.select_session(options.session_id)
            selection = _selection(reader, session, options)
            _preflight_selection(reader, selection)
            state = ArchiveMarketState()
            prime_sequence = _prime_to_start(
                reader,
                state,
                selection,
                require_checkpoint_pairs=options.start_at_ms is not None,
            )
            clock = ReplayClock(selection.start_at_ms, selection.end_at_ms)
            broker_rng = random.Random(_derived_seed(options.seed, "broker"))
            strategy_rng = random.Random(_derived_seed(options.seed, "strategy"))
            paper_broker = PaperBroker(
                config,
                state,
                state,
                rng=broker_rng,
                clock=clock,
            )
            planning_context = BotContext(
                config=config,
                broker=RejectingPlanningBroker(),
                markets=state,
                books=state,
                wallet_activity=RejectingWalletActivityClient(),
                positions=RejectingPositionClient(),
                clock=clock,
                rng=strategy_rng,
            )
            effective_start, prime_sequence = await _advance_to_replayable_start(
                reader,
                bot,
                planning_context,
                state,
                clock,
                selection,
                prime_sequence,
                explicit_start=options.start_at_ms is not None,
            )
            if effective_start != selection.start_at_ms:
                selection = BacktestSelection(
                    session_id=selection.session_id,
                    start_at_ms=effective_start,
                    end_at_ms=selection.end_at_ms,
                    market_slugs=selection.market_slugs,
                    replay_cutoff_sequence=selection.replay_cutoff_sequence,
                    session_integrity_status=(
                        selection.session_integrity_status
                    ),
                    uses_partial_session=selection.uses_partial_session,
                )
            results_dir = options.results_dir or _default_results_dir(
                options.archive_path,
                config.name,
            )
            artifacts = PerformanceArtifacts(
                results_dir,
                provenance=RunProvenance(
                    kind=PerformanceRunKind.BACKTEST,
                    bot_spec=bot_spec,
                    configuration=config,
                    seed=options.seed,
                    archive_sha256=_sha256(options.archive_path),
                    archive_schema_version=reader.schema_version,
                    archive_target_identity=reader.target_identity,
                ),
                selection=RunSelection(
                    session_id=selection.session_id,
                    start_ms=selection.start_at_ms,
                    end_ms=selection.end_at_ms,
                    market_slugs=selection.market_slugs,
                    replay_cutoff_sequence=selection.replay_cutoff_sequence,
                    session_integrity_status=(
                        selection.session_integrity_status.value
                    ),
                    uses_partial_session=selection.uses_partial_session,
                ),
                initial_cash_usdc=config.paper_portfolio_usdc,
                report_interval_ms=options.report_interval_ms,
                max_book_age_ms=config.event_max_age_ms,
            )
            for book in state.books.values():
                artifacts.record_book(book)
            artifacts.start(clock.now_ms(), paper_broker.portfolio)
            broker = BacktestPerformanceBroker(
                paper_broker,
                clock=clock,
                artifacts=artifacts,
                portfolio=paper_broker.portfolio,
            )
            ctx = BotContext(
                config=config,
                broker=broker,
                markets=state,
                books=state,
                wallet_activity=RejectingWalletActivityClient(),
                positions=RejectingPositionClient(),
                clock=clock,
                rng=strategy_rng,
            )
            runner = BotRunner(bot, ctx, now_ms_fn=clock.now_ms)
            events = reader.iter_events(
                start_at_ms=selection.start_at_ms,
                end_at_ms=selection.end_at_ms,
                session_id=selection.session_id,
                market_slugs=selection.market_slugs,
            )
            scheduler = ReplayScheduler(
                bot=bot,
                runner=runner,
                paper_broker=paper_broker,
                state=state,
                clock=clock,
                cursor=ReplayCursor(events, after_sequence=prime_sequence),
                artifacts=artifacts,
            )
            try:
                await scheduler.run()
            except asyncio.CancelledError:
                artifacts.finalize(
                    status=PerformanceRunStatus.CANCELLED,
                    ended_at_ms=clock.now_ms(),
                    portfolio=paper_broker.portfolio,
                )
                raise
            except BaseException as error:
                artifacts.finalize(
                    status=PerformanceRunStatus.FAILED,
                    ended_at_ms=clock.now_ms(),
                    portfolio=paper_broker.portfolio,
                    error=f"{type(error).__name__}: {error}",
                )
                raise
            artifacts.finalize(
                status=PerformanceRunStatus.COMPLETED,
                ended_at_ms=clock.now_ms(),
                portfolio=paper_broker.portfolio,
            )
            return BacktestResult(
                selection=selection,
                results_dir=Path(results_dir),
                event_count=scheduler.event_count,
                accepted_dispatch_count=scheduler.accepted_dispatch_count,
                skipped_dispatch_count=scheduler.skipped_dispatch_count,
                resolution_count=scheduler.resolution_count,
            )
        except ArchiveCoverageError as error:
            raise BacktestError(
                BacktestFailureReason.COVERAGE_GAP,
                str(error),
            ) from error
        except ArchiveFormatError as error:
            raise BacktestError(
                BacktestFailureReason.INVALID_SELECTION,
                str(error),
            ) from error
        except ArchiveIntegrityError as error:
            raise BacktestError(
                BacktestFailureReason.UNSUPPORTED_ARCHIVE,
                str(error),
            ) from error


def _selection(
    reader: RecordingReader,
    session: RecordingSession,
    options: BacktestOptions,
) -> BacktestSelection:
    effective_end_at_ms = _replayable_session_end(reader, session)
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
        effective_end_at_ms
        if options.end_at_ms is None
        else options.end_at_ms
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
    available_markets = reader.markets_at(
        requested_end,
        session_id=session.session_id,
        allow_gaps=True,
    )
    available_slugs = tuple(
        sorted({market.market_slug for market in available_markets})
    )
    selected_slugs = options.market_slugs or available_slugs
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
    bounds = reader.event_bounds(
        start_at_ms=requested_start,
        end_at_ms=requested_end,
        session_id=session.session_id,
        market_slugs=selected_slugs,
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
        replay_cutoff_sequence=reader.replay_cutoff_sequence,
        session_integrity_status=session.integrity_status,
        uses_partial_session=(
            session.integrity_status is not SessionIntegrityStatus.COMPLETE
        ),
    )


def _replayable_session_end(
    reader: RecordingReader,
    session: RecordingSession,
) -> int | None:
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
    durable_end_at_ms = reader.session_durable_end_at_ms(session.session_id)
    if durable_end_at_ms is None:
        return None
    if session.ended_at_ms is None:
        return durable_end_at_ms
    return min(session.ended_at_ms, durable_end_at_ms)


def _preflight_selection(
    reader: RecordingReader,
    selection: BacktestSelection,
) -> None:
    baseline_tokens: dict[tuple[str, int], set[str]] = {}
    events = reader.iter_events(
        start_at_ms=selection.start_at_ms,
        end_at_ms=selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
    )
    for event in events:
        if not isinstance(event.payload, BookBaselinePayload):
            continue
        condition_id = None if event.identity is None else event.identity.condition_id
        if condition_id is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"book baseline event {event.sequence} has no market identity",
            )
        baseline_tokens.setdefault(
            (condition_id, event.subscription_generation),
            set(),
        ).add(event.payload.token_id)

    prime_at_ms = selection.start_at_ms - 1
    markets = reader.markets_at(
        selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
    )
    for market in markets:
        required_tokens = {outcome.token_id for outcome in market.outcomes}
        if any(
            condition_id == market.condition_id
            and required_tokens.issubset(tokens)
            for (condition_id, _), tokens in baseline_tokens.items()
        ):
            continue
        checkpoint_pair = (
            None
            if prime_at_ms < 0
            else reader.checkpoint_pair_before(
                market.condition_id,
                prime_at_ms,
                session_id=selection.session_id,
            )
        )
        if checkpoint_pair is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                "selected market has no complete two-token baseline or checkpoint: "
                f"{market.market_slug}",
            )


def _prime_to_start(
    reader: RecordingReader,
    state: ArchiveMarketState,
    selection: BacktestSelection,
    *,
    require_checkpoint_pairs: bool,
) -> int:
    prime_at_ms = selection.start_at_ms - 1
    markets = (
        ()
        if prime_at_ms < 0
        else reader.markets_at(
            prime_at_ms,
            session_id=selection.session_id,
            market_slugs=selection.market_slugs,
        )
    )
    for market in markets:
        state.add_metadata(market)
    checkpoint_sequences: dict[str, int] = {}
    scan_start_ms = selection.start_at_ms
    for market in markets:
        checkpoints = reader.checkpoint_pair_before(
            market.condition_id,
            prime_at_ms,
            session_id=selection.session_id,
        )
        if checkpoints is None:
            bounds = reader.event_bounds(
                end_at_ms=selection.start_at_ms,
                session_id=selection.session_id,
                market_slugs=(market.market_slug,),
            )
            if (
                require_checkpoint_pairs
                and bounds is not None
                and bounds.start_at_ms < selection.start_at_ms
            ):
                raise BacktestError(
                    BacktestFailureReason.MISSING_MARKET_DATA,
                    "mid-session replay requires a common two-token checkpoint "
                    f"for {market.market_slug}",
                )
            scan_start_ms = min(scan_start_ms, _session_start(reader, selection.session_id))
            continue
        state.seed_checkpoints(checkpoints)
        checkpoint_sequences[market.condition_id] = checkpoints[0].sequence
        scan_start_ms = min(scan_start_ms, checkpoints[0].observed_at_ms)
    prime_sequence = max(checkpoint_sequences.values(), default=0)
    events = reader.iter_events(
        start_at_ms=scan_start_ms,
        end_at_ms=selection.start_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
        # Each market's priming interval was validated above.
        # The merged scan can begin before another market's checkpoint, so a
        # set-wide gap check here would reject an otherwise clean subrange.
        allow_gaps=True,
    )
    for event in events:
        if event.observed_at_ms >= selection.start_at_ms:
            continue
        prime_sequence = max(prime_sequence, event.sequence)
        condition_id = None if event.identity is None else event.identity.condition_id
        if event.sequence <= checkpoint_sequences.get(condition_id or "", 0):
            continue
        if isinstance(event.payload, MarketMetadataPayload):
            continue
        state.apply(event)
    return prime_sequence


async def _advance_to_replayable_start(
    reader: RecordingReader,
    bot: BaseBot,
    ctx: BotContext,
    state: ArchiveMarketState,
    clock: ReplayClock,
    selection: BacktestSelection,
    prime_sequence: int,
    *,
    explicit_start: bool,
) -> tuple[int, int]:
    if await _plan_is_replayable(bot, ctx, state):
        return selection.start_at_ms, prime_sequence
    events = reader.iter_events(
        start_at_ms=selection.start_at_ms,
        end_at_ms=selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
    )
    for event in events:
        if event.sequence <= prime_sequence:
            continue
        if explicit_start and event.observed_at_ms > selection.start_at_ms:
            break
        clock.move_to(event.observed_at_ms)
        state.apply(event)
        prime_sequence = event.sequence
        if await _plan_is_replayable(bot, ctx, state):
            return event.observed_at_ms, prime_sequence
    if explicit_start:
        raise BacktestError(
            BacktestFailureReason.MISSING_MARKET_DATA,
            "selected start has no complete books for the bot's current markets",
        )
    raise BacktestError(
        BacktestFailureReason.MISSING_MARKET_DATA,
        "recording never provides complete books for the bot's current markets",
    )


async def _plan_is_replayable(
    bot: BaseBot,
    ctx: BotContext,
    state: ArchiveMarketState,
) -> bool:
    now_ms = ctx.clock.now_ms()
    current = await bot.current_stream_rules(ctx, now_ms)
    next_rules = await bot.next_stream_rules(ctx, now_ms)
    if any(rule.wallet_addresses for rule in (*current, *next_rules)):
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            "wallet stream rules cannot be replayed from a market-only archive",
        )
    current_slugs = {
        slug for rule in current for slug in rule.market_slugs
    }
    if current_slugs:
        return all(state.has_complete_book(slug) for slug in current_slugs)
    return any(state.has_complete_book(slug) for slug in state.market_slugs)


def _session_start(reader: RecordingReader, session_id: int) -> int:
    return reader.select_session(session_id).started_at_ms


def _derived_seed(seed: int, purpose: str) -> int:
    digest = hashlib.sha256(f"{seed}:{purpose}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _default_results_dir(archive_path: Path, bot_name: str) -> Path:
    safe_name = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in bot_name
    ).strip("-") or "bot"
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    suffix = time.time_ns() % 1_000_000_000
    return Path("backtest-results") / (
        f"{archive_path.stem}-{safe_name}-{timestamp}-{suffix:09d}"
    )
