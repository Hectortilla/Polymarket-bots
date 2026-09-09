"""HTTP recovery orchestration with one request and session-factory owner."""

import asyncio
from time import monotonic

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.config import AuthSettings
from api.auth.cookies import SessionCookie
from api.auth.mail import (
    EMAIL_DELIVERY_UNAVAILABLE_DETAIL,
    AccountMailer,
    MailDeliveryError,
)
from api.auth.mail.config import MailConfigurationError
from api.auth.passwords import hash_password
from api.auth.policy import RATE_LIMIT_DETAIL
from api.auth.recovery.contracts import AccountActionResponse, RedeemRequest
from api.auth.recovery.errors import InvalidAccountToken
from api.auth.recovery.policy import (
    ACCOUNT_EMAIL_RATE_LIMIT_SCOPE,
    EMAIL_ATTEMPT_LIMIT,
    MAIL_RESPONSE_MIN_SECONDS,
    TOKEN_INVALID_DETAIL,
    TokenPurpose,
)
from api.auth.recovery.store import AccountCredentialStore
from api.auth.throttle import AuthRateLimiter
from api.http.protocol import RETRY_AFTER_HEADER


class AccountRecoveryHttp:
    def __init__(
        self, request: Request, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self._request = request
        self._session_factory = session_factory

    async def request_link(
        self, email: str, purpose: TokenPurpose
    ) -> AccountActionResponse:
        allowed, retry_after = await AuthRateLimiter(
            self._request.app.state.redis
        ).check(
            ACCOUNT_EMAIL_RATE_LIMIT_SCOPE,
            email,
            EMAIL_ATTEMPT_LIMIT,
        )
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                RATE_LIMIT_DETAIL,
                headers={RETRY_AFTER_HEADER: str(retry_after)},
            )
        request_started_at = monotonic()
        try:
            mailer = await AccountMailer.for_app(self._request.app)
            async with self._session_factory() as session:
                account_token = await AccountCredentialStore(session).issue_link(
                    email, purpose
                )
            # A delivered link must already be durable. Explicit resend creates a
            # replacement even after ambiguous SMTP acceptance or a lost response.
            await mailer.send_link(email, purpose, account_token)
        except (MailConfigurationError, MailDeliveryError):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, EMAIL_DELIVERY_UNAVAILABLE_DETAIL
            ) from None
        finally:
            # Mitigate ordinary lookup/write timing differences without blocking the loop.
            await asyncio.sleep(
                max(0, MAIL_RESPONSE_MIN_SECONDS - (monotonic() - request_started_at))
            )
        return AccountActionResponse(accepted=True)

    async def redeem(
        self, body: RedeemRequest, response: Response, purpose: TokenPurpose
    ) -> AccountActionResponse:
        password_hash = await hash_password(body.new_password.get_secret_value())
        async with self._session_factory() as session:
            try:
                await AccountCredentialStore(session).redeem(
                    body.account_token, purpose, password_hash
                )
            except InvalidAccountToken:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, TOKEN_INVALID_DETAIL
                ) from None
        SessionCookie(AuthSettings.for_app(self._request.app)).clear(response)
        return AccountActionResponse(accepted=True)
