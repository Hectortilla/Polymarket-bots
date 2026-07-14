"""Environment parsing for typed stream rules."""

import json
import os
import re
from typing import Final

from polybot.framework.streams import StreamRelation, StreamRule

from .constants import BOT_STREAM_RULES_ENV

WALLET_ADDRESS_PATTERN: Final = re.compile(r"0x[a-fA-F0-9]{40}\Z")


def env_stream_rules() -> tuple[StreamRule, ...]:
    raw = os.getenv(BOT_STREAM_RULES_ENV)
    if raw is None or not raw.strip():
        return ()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{BOT_STREAM_RULES_ENV} must be valid JSON") from error
    if not isinstance(values, list):
        raise ValueError(f"{BOT_STREAM_RULES_ENV} must be a JSON array")
    rules: list[StreamRule] = []
    for value in values:
        if not isinstance(value, dict) or set(value) - {
            "relation",
            "market_slugs",
            "wallet_addresses",
        }:
            raise ValueError("stream rules contain unsupported fields")
        relation = value.get("relation")
        markets = value.get("market_slugs", [])
        wallets = value.get("wallet_addresses", [])
        if (
            not isinstance(relation, str)
            or not isinstance(markets, list)
            or not isinstance(wallets, list)
        ):
            raise ValueError("stream rules have invalid field types")
        if not all(isinstance(item, str) for item in [*markets, *wallets]):
            raise ValueError("stream rule selectors must be strings")
        if any(WALLET_ADDRESS_PATTERN.fullmatch(wallet) is None for wallet in wallets):
            raise ValueError(
                "stream rule wallet addresses must be 0x-prefixed addresses"
            )
        rules.append(
            StreamRule(StreamRelation(relation), tuple(markets), tuple(wallets))
        )
    return tuple(dict.fromkeys(rules))
