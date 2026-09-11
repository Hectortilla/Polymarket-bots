"""Live dashboard sample projection, independent of durable runtime events."""

from datetime import datetime
from uuid import UUID

from polybot.dashboard.contracts import DashboardSample, WalletChartPoint

from api.events.contracts import (
    EquityChartPayload,
    LiveEquityChartEvent,
    LiveMarketChartEvent,
    LiveRunEvent,
    LiveWalletChartEvent,
    MarketChartPayload,
    WalletChartPayload,
)
from api.events.contracts.payloads.chart import WalletChartPointPayload


def project_live_chart_events(
    run_id: UUID,
    sample: DashboardSample,
    wallet_points: tuple[WalletChartPoint, ...],
    *,
    occurred_at: datetime,
) -> tuple[LiveRunEvent, ...]:
    return (
        LiveMarketChartEvent(
            run_id=run_id,
            occurred_at=occurred_at,
            payload=MarketChartPayload.from_sample(sample),
        ),
        LiveEquityChartEvent(
            run_id=run_id,
            occurred_at=occurred_at,
            payload=EquityChartPayload.from_sample(sample),
        ),
        LiveWalletChartEvent(
            run_id=run_id,
            occurred_at=occurred_at,
            payload=WalletChartPayload(
                sampled_at_ms=sample.sampled_at_ms,
                points=tuple(
                    WalletChartPointPayload.from_point(point) for point in wallet_points
                ),
            ),
        ),
    )
