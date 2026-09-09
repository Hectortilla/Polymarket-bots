"""Discoverable resource admission errors and retry semantics."""

from fastapi import status

from api.http.contracts import ErrorResponse
from api.http.protocol import MIN_RETRY_AFTER_SECONDS, RETRY_AFTER_HEADER

RESOURCE_LIMIT_RESPONSES = {
    code: {
        "model": ErrorResponse,
        "headers": {
            RETRY_AFTER_HEADER: {
                "description": "Suggested seconds before retrying temporary resource admission",
                "schema": {"type": "integer", "minimum": MIN_RETRY_AFTER_SECONDS},
            }
        },
    }
    for code in (status.HTTP_429_TOO_MANY_REQUESTS, status.HTTP_503_SERVICE_UNAVAILABLE)
}
