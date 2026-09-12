"""Dependency-light market selection constraints shared by HTTP and catalog."""

from typing import Annotated

from pydantic import StringConstraints

from api.limits.policy import PAPER_BETA

type MarketSlug = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
]

MAX_SELECTED_MARKETS = PAPER_BETA.tracked_markets_per_run

MIN_SELECTED_MARKETS = 1
