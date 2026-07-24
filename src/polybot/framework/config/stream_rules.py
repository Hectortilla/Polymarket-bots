"""Environment parsing for typed stream rules."""

import os

from polybot.framework.streams import StreamRule
from polybot.persistence.json_codec import loads_json

from .constants import BOT_STREAM_RULES_ENV


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
        rules.append(StreamRule.from_dict(value))
    return tuple(dict.fromkeys(rules))


def parse_stream_rules_json(raw: str) -> tuple[StreamRule, ...]:
    try:
        return parse_stream_rules(loads_json(raw))
    except (ValueError, TypeError) as error:
        raise ValueError(f"{BOT_STREAM_RULES_ENV} must be valid JSON") from error
