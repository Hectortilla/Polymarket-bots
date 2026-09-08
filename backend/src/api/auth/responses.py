"""Generated HTTP error contracts for authentication boundaries."""

from fastapi import status

from api.auth.policy import MIN_RETRY_AFTER_SECONDS
from api.http.contracts import ErrorResponse
from api.http.protocol import RETRY_AFTER_HEADER
from api.http.responses import SERVICE_UNAVAILABLE_RESPONSE

AUTH_REQUIRED_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    **SERVICE_UNAVAILABLE_RESPONSE,
}
AUTH_ATTEMPT_RESPONSES = {
    status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "headers": {
            RETRY_AFTER_HEADER: {
                "description": "Seconds until another authentication attempt is allowed",
                "schema": {"type": "integer", "minimum": MIN_RETRY_AFTER_SECONDS},
            }
        },
    },
}
