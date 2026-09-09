"""SMTP adapter: only sanitized failures leave the blocking transport boundary."""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Self

from starlette.applications import Starlette

from api.auth.config import AuthSettings
from api.auth.mail.config import SMTP_TIMEOUT_SECONDS, SmtpSecurity, SmtpSettings
from api.auth.recovery.policy import TOKEN_LIFETIME_SECONDS, TokenPurpose
from api.auth.recovery.tokens import AccountToken

ACCOUNT_MAILER_STATE_KEY = "account_mailer"
EMAIL_DELIVERY_UNAVAILABLE_DETAIL = "Email delivery is unavailable. Try again later."


class MailDeliveryError(Exception):
    """The relay did not confirm acceptance of the account email."""


class AccountMailer:
    def __init__(self, settings: SmtpSettings, auth: AuthSettings) -> None:
        self._settings = settings
        self._origin = auth.origin

    @classmethod
    async def for_app(cls, app: Starlette) -> Self:
        mailer = getattr(app.state, ACCOUNT_MAILER_STATE_KEY, None)
        if mailer is None:
            auth_settings = AuthSettings.for_app(app)
            smtp_settings = await asyncio.to_thread(
                SmtpSettings.from_env, auth_settings
            )
            mailer = cls(smtp_settings, auth_settings)
            setattr(app.state, ACCOUNT_MAILER_STATE_KEY, mailer)
        return mailer

    async def send_link(
        self, email: str, purpose: TokenPurpose, token: AccountToken
    ) -> None:
        link = purpose.email_link(self._origin, token.value)
        message = EmailMessage()
        message["From"] = self._settings.sender
        message["To"] = email
        message["Subject"] = "Polybot account link"
        message.set_content(
            "Someone requested a Polybot account link for this address. "
            f"If your account is eligible, use this single-use link within {TOKEN_LIFETIME_SECONDS // 60} minutes "
            "to choose a password and complete the request.\n\n"
            f"{link}\n\n"
            "If you did not request this, ignore this email. "
            "Your account has not been changed."
        )
        await asyncio.to_thread(self._send, message)

    def _send(self, message: EmailMessage) -> None:
        settings = self._settings
        try:
            context = ssl.create_default_context()
            if settings.security is SmtpSecurity.TLS:
                connection = smtplib.SMTP_SSL(
                    settings.host,
                    settings.port,
                    timeout=SMTP_TIMEOUT_SECONDS,
                    context=context,
                )
            else:
                connection = smtplib.SMTP(
                    settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS
                )
            with connection:
                if settings.security is SmtpSecurity.STARTTLS:
                    connection.starttls(context=context)
                if settings.username is not None:
                    connection.login(
                        settings.username.get_secret_value(),
                        settings.password.get_secret_value(),
                    )
                connection.send_message(message)
        except (OSError, smtplib.SMTPException):
            raise MailDeliveryError(EMAIL_DELIVERY_UNAVAILABLE_DETAIL) from None
