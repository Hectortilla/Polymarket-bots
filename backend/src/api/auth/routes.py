"""Local email/password account and session endpoints."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.auth.config import AuthSettings
from api.auth.contracts import (
    Credentials,
    CurrentUser,
    LoginCredentials,
    LogoutResponse,
)
from api.auth.cookies import SessionCookie
from api.auth.dependencies import CurrentUserDependency
from api.auth.passwords import DUMMY_HASH, hash_password, verify_password
from api.auth.policy import (
    CURRENT_USER_OPERATION_ID,
    LOGIN_FAILED_DETAIL,
    LOGIN_OPERATION_ID,
    LOGIN_PATH,
    LOGOUT_OPERATION_ID,
    LOGOUT_PATH,
    ME_PATH,
    REGISTER_FAILED_DETAIL,
    REGISTER_OPERATION_ID,
    REGISTER_PATH,
)
from api.auth.responses import AUTH_ATTEMPT_RESPONSES
from api.auth.store import AuthStore
from api.auth.store.errors import RegistrationConflictError
from api.http.dependencies import SessionFactoryDependency
from api.http.responses import CONFLICT_RESPONSE

router = APIRouter()


@router.post(
    REGISTER_PATH,
    response_model=CurrentUser,
    status_code=status.HTTP_201_CREATED,
    operation_id=REGISTER_OPERATION_ID,
    responses={**AUTH_ATTEMPT_RESPONSES, **CONFLICT_RESPONSE},
)
async def register(
    credentials: Credentials,
    request: Request,
    response: Response,
    session_factory: SessionFactoryDependency,
) -> CurrentUser:
    password_hash = await hash_password(credentials.password.get_secret_value())
    async with session_factory() as session:
        store = AuthStore(session)
        try:
            user = await store.register(credentials.email, password_hash)
            token = await store.issue_session(user, SessionCookie.read(request))
        except RegistrationConflictError:
            await session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, REGISTER_FAILED_DETAIL
            ) from None
    SessionCookie(AuthSettings.for_app(request.app)).issue(response, token)
    return CurrentUser.from_model(user)


@router.post(
    LOGIN_PATH,
    response_model=CurrentUser,
    operation_id=LOGIN_OPERATION_ID,
    responses=AUTH_ATTEMPT_RESPONSES,
)
async def login(
    credentials: LoginCredentials,
    request: Request,
    response: Response,
    session_factory: SessionFactoryDependency,
) -> CurrentUser:
    async with session_factory() as session:
        store = AuthStore(session)
        # Verify eligibility after the account lock serializes with password changes
        # and suspension; neither can leave a newly issued session behind.
        user = await store.find_user(credentials.email, lock=True)
        valid = await verify_password(
            DUMMY_HASH if user is None else user.password_hash,
            credentials.password.get_secret_value(),
        )
        if not valid or user is None or not user.access_allowed:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED_DETAIL)
        token = await store.issue_session(user, SessionCookie.read(request))
    SessionCookie(AuthSettings.for_app(request.app)).issue(response, token)
    return CurrentUser.from_model(user)


@router.post(
    LOGOUT_PATH, response_model=LogoutResponse, operation_id=LOGOUT_OPERATION_ID
)
async def logout(
    request: Request, response: Response, session_factory: SessionFactoryDependency
) -> LogoutResponse:
    async with session_factory() as session:
        await AuthStore(session).revoke(SessionCookie.read(request))
        await session.commit()
    SessionCookie(AuthSettings.for_app(request.app)).clear(response)
    return LogoutResponse(logged_out=True)


@router.get(ME_PATH, response_model=CurrentUser, operation_id=CURRENT_USER_OPERATION_ID)
async def me(user: CurrentUserDependency) -> CurrentUser:
    return user
