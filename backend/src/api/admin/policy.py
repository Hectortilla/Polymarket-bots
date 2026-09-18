"""Admin routing and bounded browsing contracts."""

ADMIN_PATH = "/admin"
ADMIN_LOGIN_REDIRECT = "/login?returnTo=/admin/"
ADMIN_REQUIRED_DETAIL = "administrator access required"
ADMIN_READ_ONLY_DETAIL = "admin panel is read-only"
ADMIN_SEARCH_MAX_LENGTH = 254
ADMIN_PAGE_SIZE = 25
ADMIN_PAGE_SIZE_OPTIONS = (25, 50, 100)
OWNER_FILTER = "owner_user_id"
BOT_FILTER = "bot_id"
STATUS_FILTER = "status"
OWNER_DISPLAY = "owner"

USER_VIEW_ID = "user-row"
CONFIGURATION_VIEW_ID = "bot-row"
RUN_VIEW_ID = "run-row"
