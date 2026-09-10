"""Freshness policy for private operational feed observations."""

from api.operations.telemetry.keys import OPERATIONS_TELEMETRY_KEY_NAMESPACE

FEED_TTL_SECONDS = 45
FEED_KEY_PREFIX = OPERATIONS_TELEMETRY_KEY_NAMESPACE + "feed:"
