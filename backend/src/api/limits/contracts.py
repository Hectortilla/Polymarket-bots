"""Authenticated account usage, without other accounts' resource information."""

from pydantic import BaseModel, ConfigDict, NonNegativeInt

from api.limits.policy import PaperBetaPolicy


class AccountUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: PaperBetaPolicy
    active_runs: NonNegativeInt
    queued_runs: NonNegativeInt
    saved_bots: NonNegativeInt
    saved_templates: NonNegativeInt
    retained_runs: NonNegativeInt
