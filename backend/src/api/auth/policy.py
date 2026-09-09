"""Approved Slice 15 authentication policy and public route inventory."""

from http import HTTPMethod

from api.http.routes.paths import API_PREFIX, HEALTH_PATH

PASSWORD_MIN_LENGTH = 15
PASSWORD_MAX_LENGTH = 128
EMAIL_MAX_LENGTH = 254
ARGON_MEMORY_KIB = 19 * 1024
ARGON_ITERATIONS = 2
ARGON_PARALLELISM = 1
SESSION_LIFETIME_SECONDS = 7 * 24 * 60 * 60
SESSION_RECHECK_SECONDS = 15
SESSION_TOKEN_BYTES = 32
SESSION_COOKIE = "polybot_session"
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_SAMESITE = "lax"
CSRF_SAFE_METHODS = (HTTPMethod.GET, HTTPMethod.HEAD, HTTPMethod.OPTIONS)
AUTH_BODY_MAX_BYTES = 4096
AUTH_RATE_WINDOW_SECONDS = 15 * 60
AUTH_RATE_LIMIT_KEY_PREFIX = "polybot:auth:attempts:"
LOGIN_ATTEMPT_LIMIT = 10
REGISTER_ATTEMPT_LIMIT = 5
REGISTER_PATH = "/auth/register"
LOGIN_PATH = "/auth/login"
LOGOUT_PATH = "/auth/logout"
ME_PATH = "/auth/me"
REGISTER_OPERATION_ID = "register"
LOGIN_OPERATION_ID = "login"
LOGOUT_OPERATION_ID = "logout"
CURRENT_USER_OPERATION_ID = "currentUser"
PUBLIC_ROUTES = frozenset(
    {
        (HTTPMethod.POST, API_PREFIX + REGISTER_PATH),
        (HTTPMethod.POST, API_PREFIX + LOGIN_PATH),
        (HTTPMethod.POST, API_PREFIX + LOGOUT_PATH),
        (HTTPMethod.GET, API_PREFIX + HEALTH_PATH),
    }
)
AUTH_ATTEMPT_LIMITS = {
    API_PREFIX + REGISTER_PATH: REGISTER_ATTEMPT_LIMIT,
    API_PREFIX + LOGIN_PATH: LOGIN_ATTEMPT_LIMIT,
}
AUTH_CREDENTIAL_PATHS = frozenset(AUTH_ATTEMPT_LIMITS)
AUTH_REQUIRED_DETAIL = "authentication required"
LOGIN_FAILED_DETAIL = "invalid email or password"
REGISTER_FAILED_DETAIL = "registration unavailable for these credentials"
CSRF_FAILED_DETAIL = "same-origin JSON request required"
RATE_LIMIT_DETAIL = "too many authentication attempts"
AUTH_BODY_TOO_LARGE_DETAIL = "authentication request too large"
