import asyncio
from types import SimpleNamespace

import pytest

from polybot.cli.followed_wallets.tracker import FollowedWalletTracker
from polybot.cli.observability.bootstrap import BootstrapProgressAdapter
from polybot.cli.observability.events import (
    BootstrapPhase,
    BootstrapProgress,
)


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


def test_market_adapter_reports_cumulative_unique_slug_progress() -> None:
    class Gamma:
        async def find_many(self, slugs):
            return tuple(
                None if slug == "missing" else SimpleNamespace(slug=slug)
                for slug in slugs
            )

    observer = RecordingObserver()
    adapter = BootstrapProgressAdapter(observer)  # type: ignore[arg-type]
    adapter.begin_cycle()
    resolver = adapter.wrap_gamma(Gamma())  # type: ignore[arg-type]

    asyncio.run(resolver.find_many(("first", "missing", "first")))
    asyncio.run(resolver.find_many(("first", "second")))

    assert [
        (event.phase, event.completed, event.total)
        for event in observer.events
        if isinstance(event, BootstrapProgress)
    ] == [
        (BootstrapPhase.MARKETS, 0, 0),
        (BootstrapPhase.MARKETS, 0, 2),
        (BootstrapPhase.MARKETS, 1, 2),
        (BootstrapPhase.MARKETS, 1, 3),
        (BootstrapPhase.MARKETS, 2, 3),
    ]


def test_bootstrap_progress_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        BootstrapProgress(BootstrapPhase.MARKETS, -1, 0)
    with pytest.raises(ValueError, match="cannot exceed"):
        BootstrapProgress(BootstrapPhase.WALLETS, 2, 1)


def test_wallet_adapter_reports_each_completed_bootstrap(tmp_path) -> None:
    observer = RecordingObserver()
    adapter = BootstrapProgressAdapter(observer)  # type: ignore[arg-type]
    adapter.begin_cycle()
    tracker = adapter.wrap_followed_wallets(
        FollowedWalletTracker(tmp_path / "follow.json"),
        total_wallets=2,
    )

    assert tracker.synchronize(("wallet-a", "wallet-b")) == (
        "wallet-a",
        "wallet-b",
    )
    tracker.bootstrap("wallet-a", ())
    tracker.bootstrap("wallet-b", ())

    assert [
        (event.phase, event.completed, event.total)
        for event in observer.events
        if isinstance(event, BootstrapProgress)
        and event.phase is BootstrapPhase.WALLETS
    ] == [
        (BootstrapPhase.WALLETS, 0, 2),
        (BootstrapPhase.WALLETS, 1, 2),
        (BootstrapPhase.WALLETS, 2, 2),
    ]
