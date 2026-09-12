"""Shared request bounds for public discovery selectors."""

from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MIN_DISCOVERY_SEARCH_LENGTH = 2
MAX_DISCOVERY_SEARCH_LENGTH = 200
DEFAULT_DISCOVERY_SEARCH_LIMIT = 12
MAX_DISCOVERY_SEARCH_LIMIT = 20


class DiscoverySearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=MIN_DISCOVERY_SEARCH_LENGTH,
            max_length=MAX_DISCOVERY_SEARCH_LENGTH,
        ),
    ]
    limit: int = Field(
        default=DEFAULT_DISCOVERY_SEARCH_LIMIT, ge=1, le=MAX_DISCOVERY_SEARCH_LIMIT
    )
