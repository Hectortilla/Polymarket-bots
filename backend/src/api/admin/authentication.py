"""Session authorization before entering the mounted SQLAdmin application."""

from fastapi import HTTPException, Request
from sqladmin.authentication import AuthenticationBackend
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from api.admin.policy import (
    ADMIN_LOGIN_REDIRECT,
    ADMIN_PATH,
    ADMIN_READ_ONLY_DETAIL,
    ADMIN_REQUIRED_DETAIL,
)
from api.auth.dependencies import current_user


class AdminBoundaryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == ADMIN_PATH or path.startswith(ADMIN_PATH + "/")
        ):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        try:
            request.state.user = await current_user(request)
        except HTTPException as error:
            if error.status_code != 401:
                raise
            await RedirectResponse(ADMIN_LOGIN_REDIRECT, status_code=302)(
                scope, receive, send
            )
            return
        if not request.state.user.is_admin:
            await PlainTextResponse(ADMIN_REQUIRED_DETAIL, status_code=403)(
                scope, receive, send
            )
            return
        if request.method not in {"GET", "HEAD"}:
            await PlainTextResponse(ADMIN_READ_ONLY_DETAIL, status_code=405)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


class ExistingSessionAuthentication(AuthenticationBackend):
    def __init__(self) -> None:
        # The application's opaque cookie is the only session authority.
        self.middlewares = []

    async def authenticate(self, request: Request) -> bool:
        user = getattr(request.state, "user", None)
        return user is not None and user.is_admin

    async def login(self, request: Request):
        return RedirectResponse(ADMIN_LOGIN_REDIRECT, status_code=302)

    async def logout(self, request: Request):
        # GET never revokes credentials. The navigation button uses the existing POST API.
        return RedirectResponse("/account", status_code=302)
