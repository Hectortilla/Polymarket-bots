"""One host-only session-cookie policy for issuance and removal."""

from fastapi import Request, Response

from api.auth.config import AuthSettings
from api.auth.policy import (
    SESSION_COOKIE,
    SESSION_COOKIE_PATH,
    SESSION_COOKIE_SAMESITE,
    SESSION_LIFETIME_SECONDS,
)
from api.auth.store.tokens import SessionToken


class SessionCookie:
    def __init__(self, settings: AuthSettings) -> None:
        self._options = {
            "key": SESSION_COOKIE,
            "path": SESSION_COOKIE_PATH,
            "secure": settings.secure_cookie,
            "httponly": True,
            "samesite": SESSION_COOKIE_SAMESITE,
        }

    def issue(self, response: Response, token: SessionToken) -> None:
        response.set_cookie(
            value=token.value, max_age=SESSION_LIFETIME_SECONDS, **self._options
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(**self._options)

    @staticmethod
    def read(request: Request) -> SessionToken | None:
        return SessionToken.parse(request.cookies.get(SESSION_COOKIE))
