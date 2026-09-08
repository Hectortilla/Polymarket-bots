"""Dependency-light catalog identifiers and finite contract values."""

from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints


WIDGET_SCHEMA_KEY = "x-widget"

type DefinitionId = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]


class SelectionMode(StrEnum):
    USER_CONFIGURED = "user_configured"
    BOT_MANAGED = "bot_managed"
    ABSENT = "absent"


class WidgetKind(StrEnum):
    DECIMAL = "decimal"
    MARKET_SLUGS = "market_slugs"
    WALLET_ADDRESSES = "wallet_addresses"
    STREAM_RULES = "stream_rules"


class BotDefinitionLabel(StrEnum):
    STANDARD = "standard"
    EXAMPLE = "example"
    NON_TRADING = "non_trading"
