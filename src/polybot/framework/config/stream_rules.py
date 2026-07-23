"""Environment parsing for typed stream rules."""

import os

from polybot.framework.streams import StreamRelation, StreamRule
from polybot.framework.wallets import validate_wallet_address
from polybot.persistence.json_codec import loads_json

from .constants import BOT_STREAM_RULES_ENV


STREAM_RULE_RELATION_FIELD = "relation"
STREAM_RULE_MARKET_SLUGS_FIELD = "market_slugs"
STREAM_RULE_WALLET_ADDRESSES_FIELD = "wallet_addresses"
STREAM_RULE_FIELDS = frozenset(
    {
        STREAM_RULE_RELATION_FIELD,
        STREAM_RULE_MARKET_SLUGS_FIELD,
        STREAM_RULE_WALLET_ADDRESSES_FIELD,
    }
)


def env_stream_rules() -> tuple[StreamRule, ...]:
    raw = os.getenv(BOT_STREAM_RULES_ENV)
    if raw is None or not raw.strip():
        return ()
    try:
        values = loads_json(raw)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{BOT_STREAM_RULES_ENV} must be valid JSON") from error
    return parse_stream_rules(values)


def parse_stream_rules(values: object) -> tuple[StreamRule, ...]:
    if not isinstance(values, list):
        raise ValueError(f"{BOT_STREAM_RULES_ENV} must be a JSON array")
    rules: list[StreamRule] = []
    for value in values:
        if not isinstance(value, dict) or set(value) - STREAM_RULE_FIELDS:
            raise ValueError("stream rules contain unsupported fields")
        relation = value.get(STREAM_RULE_RELATION_FIELD)
        markets = value.get(STREAM_RULE_MARKET_SLUGS_FIELD, [])
        wallets = value.get(STREAM_RULE_WALLET_ADDRESSES_FIELD, [])
        if (
            not isinstance(relation, str)
            or not isinstance(markets, list)
            or not isinstance(wallets, list)
        ):
            raise ValueError("stream rules have invalid field types")
        if not all(isinstance(item, str) for item in [*markets, *wallets]):
            raise ValueError("stream rule selectors must be strings")
        try:
            normalized_wallets = tuple(validate_wallet_address(wallet) for wallet in wallets)
        except ValueError as error:
            raise ValueError(
                "stream rule wallet addresses must be 0x-prefixed addresses"
            ) from error
        rules.append(
            StreamRule(StreamRelation(relation), tuple(markets), normalized_wallets)
        )
    return tuple(dict.fromkeys(rules))


def parse_stream_rules_json(raw: str) -> tuple[StreamRule, ...]:
    try:
        return parse_stream_rules(loads_json(raw))
    except (ValueError, TypeError) as error:
        raise ValueError(f"{BOT_STREAM_RULES_ENV} must be valid JSON") from error
