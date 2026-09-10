"""An authenticated user may request only their own account's deletion."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.auth.config import AuthSettings
from api.auth.cookies import SessionCookie
from api.auth.dependencies import CurrentUserDependency
from api.auth.recovery.contracts import AccountActionResponse, ReauthenticateRequest
from api.auth.recovery.errors import ReauthenticationFailed
from api.auth.recovery.policy import REAUTHENTICATION_FAILED_DETAIL
from api.http.dependencies import SessionFactoryDependency
from api.lifecycle.deletion.service import AccountDeletion
from api.lifecycle.http import ACCOUNT_DELETION_OPERATION_ID, ACCOUNT_DELETION_PATH

router = APIRouter()


@router.post(
    ACCOUNT_DELETION_PATH,
    response_model=AccountActionResponse,
    operation_id=ACCOUNT_DELETION_OPERATION_ID,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_account_deletion(
    body: ReauthenticateRequest,
    user: CurrentUserDependency,
    request: Request,
    response: Response,
    session_factory: SessionFactoryDependency,
) -> AccountActionResponse:
    async with session_factory() as session:
        try:
            await AccountDeletion(session).request(
                user.id,
                request.state.session_token,
                body.current_password.get_secret_value(),
            )
        except ReauthenticationFailed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, REAUTHENTICATION_FAILED_DETAIL
            ) from None
    SessionCookie(AuthSettings.for_app(request.app)).clear(response)
    return AccountActionResponse(accepted=True)
