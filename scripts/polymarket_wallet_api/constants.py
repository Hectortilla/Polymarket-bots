"""External API limits and query contracts for wallet scans."""

from typing import Final

GAMMA_API_BASE: Final = "https://gamma-api.polymarket.com"
GAMMA_MARKETS_PATH: Final = "/markets"
MAX_ACTIVITY_ITEMS: Final = 3_500
MAX_ACTIVITY_OFFSET: Final = 3_000
SDK_PAGE_SIZE: Final = 500
POSITION_SIZE_THRESHOLD: Final = 0.1
SINGLE_RESULT_PAGE_SIZE: Final = 1
DEFAULT_MARKET_POSITION_LIMIT: Final = SDK_PAGE_SIZE
MARKET_QUESTION_FIELD: Final = "question"
MARKET_START_DATE_FIELD: Final = "startDate"
MARKET_END_DATE_FIELD: Final = "endDate"
MARKET_ACTIVE_FIELD: Final = "active"
MARKET_CLOSED_FIELD: Final = "closed"
MARKET_WINNING_OUTCOME_FIELD: Final = "winningOutcome"
MARKET_OUTCOMES_FIELD: Final = "outcomes"
ACTIVITY_SORT_BY: Final = "TIMESTAMP"
DESCENDING_SORT: Final = "DESC"
MARKET_POSITION_STATUS: Final = "ALL"
MARKET_POSITION_SORT_BY: Final = "TOKENS"
