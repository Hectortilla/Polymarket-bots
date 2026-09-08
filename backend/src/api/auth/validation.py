"""Secret-safe projection of credential validation failures."""

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.auth.policy import AUTH_CREDENTIAL_PATHS


async def safe_validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    redact_messages = request.url.path in AUTH_CREDENTIAL_PATHS
    # Pydantic input/context fields can contain plaintext credentials.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": [
                {
                    "type": issue["type"],
                    "loc": list(issue["loc"]),
                    "msg": "Invalid input" if redact_messages else issue["msg"],
                }
                for issue in error.errors()
            ]
        },
    )
