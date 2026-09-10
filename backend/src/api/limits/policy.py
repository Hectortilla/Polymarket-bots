"""The single owning allowance contract for the free paper beta."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, PositiveInt


class PaperBetaPolicy(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )

    active_runs: PositiveInt = 1
    queued_runs: PositiveInt = 2
    global_active_runs: PositiveInt = 4
    global_queued_runs: PositiveInt = 8
    run_duration_seconds: PositiveInt = 3600
    tracked_markets_per_run: PositiveInt = 10
    followed_wallets_per_run: PositiveInt = 2
    saved_bots: PositiveInt = 20
    retained_runs: PositiveInt = 100
    history_retention_days: PositiveInt = 30
    requests_per_minute: PositiveInt = 120
    global_requests_per_minute: PositiveInt = 1200
    expensive_requests_per_minute: PositiveInt = 20
    global_expensive_requests_per_minute: PositiveInt = 120
    open_streams: PositiveInt = 3
    global_open_streams: PositiveInt = 32

    def remaining_run_seconds(self, started_at: datetime, now: datetime) -> float:
        elapsed_seconds = (now - started_at).total_seconds()
        return max(0, self.run_duration_seconds - elapsed_seconds)


PAPER_BETA = PaperBetaPolicy()
RATE_WINDOW_SECONDS = 60
STREAM_LIFETIME_SECONDS = 55
STREAM_LEASE_SECONDS = 60
