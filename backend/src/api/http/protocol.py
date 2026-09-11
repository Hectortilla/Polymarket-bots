"""Shared HTTP wire names and private cache policy."""

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
IDEMPOTENCY_RECOVERY_HEADER = "Idempotency-Recovery"
CONTENT_TYPE_HEADER = "Content-Type"
JSON_CONTENT_TYPE = "application/json"
RETRY_AFTER_HEADER = "Retry-After"
CACHE_CONTROL_HEADER = "Cache-Control"
NO_STORE_CACHE_DIRECTIVE = "no-store"

MIN_RETRY_AFTER_SECONDS = 1

ASGI_TYPE_FIELD = "type"
ASGI_HTTP_SCOPE = "http"
ASGI_HTTP_REQUEST = "http.request"
ASGI_HTTP_DISCONNECT = "http.disconnect"
ASGI_HTTP_RESPONSE_START = "http.response.start"

ASGI_HTTP_RESPONSE_BODY = "http.response.body"
ASGI_BODY_FIELD = "body"
ASGI_MORE_BODY_FIELD = "more_body"
