"""Public construction and lifecycle of one deterministic archive replay."""

from __future__ import annotations

from polybot.async_io import run_blocking
from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestOptions,
    BacktestResult,
)
from polybot.framework.base import BaseBot
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.recording.archive.errors import (
    ArchiveCoverageError,
    ArchiveFormatError,
    ArchiveIntegrityError,
    ArchiveLockedError,
    RecordingArchiveError,
)
from polybot.recording.archive.reader import RecordingReader

from .artifacts import start_backtest_artifacts
from .execution import execute_replay
from .setup import prepare_replay


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
        reader = await run_blocking(RecordingReader.for_replay, options.archive_path)
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

    try:
        try:
            prepared = await prepare_replay(reader, bot, config, options)
            started_artifacts = await start_backtest_artifacts(
                reader,
                config,
                bot_spec=bot_spec,
                options=options,
                prepared=prepared,
            )
            execution = await execute_replay(
                reader,
                bot,
                config,
                prepared=prepared,
                artifacts=started_artifacts.artifacts,
            )
            return BacktestResult(
                selection=prepared.selection,
                results_dir=started_artifacts.results_dir,
                event_count=execution.event_count,
                accepted_dispatch_count=execution.accepted_dispatch_count,
                skipped_dispatch_count=execution.skipped_dispatch_count,
                resolution_count=execution.resolution_count,
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
    finally:
        await run_blocking(reader.close)
