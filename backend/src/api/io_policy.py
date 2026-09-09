"""Bounded shared database and Redis adapter operations."""

DEPENDENCY_TIMEOUT_SECONDS = 5.0
DATABASE_CONNECT_ARGS = {
    "timeout": DEPENDENCY_TIMEOUT_SECONDS,
    "command_timeout": DEPENDENCY_TIMEOUT_SECONDS,
}
REDIS_SOCKET_OPTIONS = {
    "socket_connect_timeout": DEPENDENCY_TIMEOUT_SECONDS,
    "socket_timeout": DEPENDENCY_TIMEOUT_SECONDS,
}
