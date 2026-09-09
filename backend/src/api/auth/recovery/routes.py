"""Same-origin account-link, password and session management HTTP endpoints."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.auth.config import AuthSettings
from api.auth.contracts import EmailRequest
from api.auth.cookies import SessionCookie
from api.auth.dependencies import CurrentUserDependency
from api.auth.passwords import hash_password
from api.auth.recovery.contracts import (
    AccountActionResponse,
    AccountStatus,
    ChangePasswordRequest,
    RedeemRequest,
    RevokeSessionsRequest,
)
from api.auth.recovery.errors import ReauthenticationFailed
from api.auth.recovery.http import AccountRecoveryHttp
from api.auth.recovery.policy import (
    ACCOUNT_PATH,
    ACCOUNT_STATUS_OPERATION_ID,
    PASSWORD_CHANGE_OPERATION_ID,
    PASSWORD_CHANGE_PATH,
    REAUTHENTICATION_FAILED_DETAIL,
    RESET_COMPLETE_OPERATION_ID,
    RESET_COMPLETE_PATH,
    RESET_REQUEST_OPERATION_ID,
    RESET_REQUEST_PATH,
    SESSIONS_REVOKE_OPERATION_ID,
    SESSIONS_REVOKE_PATH,
    VERIFY_COMPLETE_OPERATION_ID,
    VERIFY_COMPLETE_PATH,
    VERIFY_REQUEST_OPERATION_ID,
    VERIFY_REQUEST_PATH,
    TokenPurpose,
)
from api.auth.recovery.store import AccountCredentialStore
from api.auth.recovery.store.persistence import CredentialRows
from api.auth.responses import AUTH_ATTEMPT_RESPONSES
from api.http.contracts import ErrorResponse
from api.http.dependencies import SessionFactoryDependency

REDEEM_RESPONSES = {status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}}

router = APIRouter(responses=AUTH_ATTEMPT_RESPONSES)


@router.get(
    ACCOUNT_PATH, response_model=AccountStatus, operation_id=ACCOUNT_STATUS_OPERATION_ID
)
async def account_status(
    user: CurrentUserDependency, session_factory: SessionFactoryDependency
) -> AccountStatus:
    async with session_factory() as session:
        return await CredentialRows(session).status(user.id)


@router.post(
    RESET_REQUEST_PATH,
    response_model=AccountActionResponse,
    operation_id=RESET_REQUEST_OPERATION_ID,
)
async def request_password_reset(
    body: EmailRequest, request: Request, session_factory: SessionFactoryDependency
) -> AccountActionResponse:
    return await AccountRecoveryHttp(request, session_factory).request_link(
        body.email, TokenPurpose.RESET
    )


@router.post(
    VERIFY_REQUEST_PATH,
    response_model=AccountActionResponse,
    operation_id=VERIFY_REQUEST_OPERATION_ID,
)
async def request_email_verification(
    body: EmailRequest, request: Request, session_factory: SessionFactoryDependency
) -> AccountActionResponse:
    return await AccountRecoveryHttp(request, session_factory).request_link(
        body.email, TokenPurpose.VERIFY
    )


@router.post(
    RESET_COMPLETE_PATH,
    response_model=AccountActionResponse,
    operation_id=RESET_COMPLETE_OPERATION_ID,
    responses=REDEEM_RESPONSES,
)
async def complete_password_reset(
    body: RedeemRequest,
    request: Request,
    response: Response,
    session_factory: SessionFactoryDependency,
) -> AccountActionResponse:
    return await AccountRecoveryHttp(request, session_factory).redeem(
        body, response, TokenPurpose.RESET
    )


@router.post(
    VERIFY_COMPLETE_PATH,
    response_model=AccountActionResponse,
    operation_id=VERIFY_COMPLETE_OPERATION_ID,
    responses=REDEEM_RESPONSES,
)
async def complete_email_verification(
    body: RedeemRequest,
    request: Request,
    response: Response,
    session_factory: SessionFactoryDependency,
) -> AccountActionResponse:
    return await AccountRecoveryHttp(request, session_factory).redeem(
        body, response, TokenPurpose.VERIFY
    )


@router.post(
    PASSWORD_CHANGE_PATH,
    response_model=AccountActionResponse,
    operation_id=PASSWORD_CHANGE_OPERATION_ID,
)
async def change_password(
    body: ChangePasswordRequest,
    user: CurrentUserDependency,
    request: Request,
    response: Response,
    session_factory: SessionFactoryDependency,
) -> AccountActionResponse:
    password_hash = await hash_password(body.new_password.get_secret_value())
    async with session_factory() as session:
        try:
            await AccountCredentialStore(session).change_password(
                user.id,
                request.state.session_token,
                body.current_password.get_secret_value(),
                password_hash,
            )
        except ReauthenticationFailed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, REAUTHENTICATION_FAILED_DETAIL
            ) from None
    SessionCookie(AuthSettings.for_app(request.app)).clear(response)
    return AccountActionResponse(accepted=True)


@router.post(
    SESSIONS_REVOKE_PATH,
    response_model=AccountActionResponse,
    operation_id=SESSIONS_REVOKE_OPERATION_ID,
)
async def revoke_sessions(
    body: RevokeSessionsRequest,
    user: CurrentUserDependency,
    request: Request,
    response: Response,
    session_factory: SessionFactoryDependency,
) -> AccountActionResponse:
    async with session_factory() as session:
        try:
            await AccountCredentialStore(session).revoke_sessions(
                user.id,
                request.state.session_token,
                body.current_password.get_secret_value(),
                body.scope,
            )
        except ReauthenticationFailed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, REAUTHENTICATION_FAILED_DETAIL
            ) from None
    if body.scope.revokes_current:
        SessionCookie(AuthSettings.for_app(request.app)).clear(response)
    return AccountActionResponse(accepted=True)
