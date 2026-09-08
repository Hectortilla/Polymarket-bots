"""One session dependency and explicit public route allowlist."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from api.auth.contracts import CurrentUser
from api.auth.cookies import SessionCookie
from api.auth.policy import AUTH_REQUIRED_DETAIL, PUBLIC_ROUTES
from api.auth.store import AuthStore


async def application_authentication(request: Request) -> None:
    if (request.method, request.url.path) not in PUBLIC_ROUTES:
        request.state.user = await current_user(request)


async def authenticated_user(request: Request) -> CurrentUser:
    return request.state.user


CurrentUserDependency = Annotated[CurrentUser, Depends(authenticated_user)]


async def current_user(request: Request) -> CurrentUser:
    token = SessionCookie.read(request)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, AUTH_REQUIRED_DETAIL)
    async with request.app.state.session_factory() as session:
        user = await AuthStore(session).current_user(token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, AUTH_REQUIRED_DETAIL)
    request.state.session_token = token
    return user
