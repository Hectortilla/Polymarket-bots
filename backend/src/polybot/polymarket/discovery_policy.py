"""Bounded network work for interactive discovery."""

import re

DISCOVERY_TIMEOUT_SECONDS = 5

CONDITION_ID_QUERY_PATTERN = re.compile(r"0x[a-fA-F0-9]{64}")
NUMERIC_MARKET_IDENTIFIER_QUERY_PATTERN = re.compile(r"[0-9]+")
IDENTIFIER_LOOKUP_PAGE_SIZE = 2
