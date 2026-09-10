"""SMTP adapter TLS, transport isolation, origin and secret-redaction contracts."""

import asyncio
import smtplib
import threading
from unittest.mock import MagicMock, patch

import pytest
from api.auth.config import AuthSettings
from api.auth.mail import ACCOUNT_LINK_SUBJECT, AccountMailer, MailDeliveryError
from api.auth.mail.config import SMTP_TIMEOUT_SECONDS, SmtpSecurity, SmtpSettings
from api.auth.recovery.policy import (
    BROWSER_RESET_PATH,
    BROWSER_VERIFY_PATH,
    TOKEN_LIFETIME_MINUTES,
    TokenPurpose,
)
from api.auth.recovery.tokens import AccountToken
from pydantic import SecretStr, ValidationError


@pytest.mark.parametrize(
    "purpose, browser_path",
    [
        (TokenPurpose.RESET, BROWSER_RESET_PATH),
        (TokenPurpose.VERIFY, BROWSER_VERIFY_PATH),
    ],
)
@pytest.mark.parametrize("security", [SmtpSecurity.STARTTLS, SmtpSecurity.TLS])
def test_smtp_uses_tls_and_keeps_blocking_work_off_the_event_loop(
    security, purpose, browser_path
):
    main_thread = threading.get_ident()
    token = AccountToken.issue()
    settings = SmtpSettings(
        host="smtp.example.com",
        port=587,
        sender="sender@example.com",
        security=security,
        username=SecretStr("user"),
        password=SecretStr("secret"),
    )
    connection = MagicMock()
    connection.__enter__.return_value = connection

    def send(message):
        assert threading.get_ident() != main_thread
        assert (
            f"https://paper.example.com{browser_path}#{token.value}"
            in message.get_content()
        )
        assert f"within {TOKEN_LIFETIME_MINUTES} minutes" in message.get_content()
        assert message["Subject"] == ACCOUNT_LINK_SUBJECT
        assert message["To"] == "owner@example.com"
        assert "secret" not in message.get_content()

    connection.send_message.side_effect = send
    factory = (
        "api.auth.mail.smtplib.SMTP_SSL"
        if security is SmtpSecurity.TLS
        else "api.auth.mail.smtplib.SMTP"
    )
    with patch(factory, return_value=connection) as create:
        asyncio.run(
            AccountMailer(
                settings, AuthSettings("https://paper.example.com")
            ).send_link("owner@example.com", purpose, token)
        )
    assert create.call_args.kwargs["timeout"] == SMTP_TIMEOUT_SECONDS
    if security is SmtpSecurity.STARTTLS:
        context = connection.starttls.call_args.kwargs["context"]
    else:
        context = create.call_args.kwargs["context"]
    assert context.check_hostname
    connection.login.assert_called_once_with("user", "secret")


def test_delivery_failure_does_not_expose_relay_payload():
    settings = SmtpSettings(
        host="smtp.example.com", port=587, sender="sender@example.com"
    )
    with patch(
        "api.auth.mail.smtplib.SMTP",
        side_effect=smtplib.SMTPException("private token recipient password"),
    ):
        with pytest.raises(MailDeliveryError) as failure:
            asyncio.run(
                AccountMailer(
                    settings, AuthSettings("https://paper.example.com")
                ).send_link(
                    "owner@example.com", TokenPurpose.RESET, AccountToken.issue()
                )
            )
        assert "private" not in str(failure.value)


@pytest.mark.parametrize(
    "host,allow_local", [("127.0.0.1", False), ("192.0.2.1", True)]
)
def test_plaintext_requires_explicit_local_loopback(host, allow_local):
    with pytest.raises(ValidationError):
        SmtpSettings(
            host=host,
            port=2525,
            sender="sender@example.com",
            security=SmtpSecurity.LOCAL,
            allow_local=allow_local,
        )


def test_tokens_hide_their_values_and_reject_invalid_shapes():
    token = AccountToken.issue()
    assert token.value not in repr(token)
    assert token.digest != token.value
    with pytest.raises(ValueError):
        AccountToken.parse("bad token")


def test_explicit_local_relay_can_send_without_tls_or_authentication():
    settings = SmtpSettings(
        host="127.0.0.1",
        port=2525,
        sender=" Sender@EXAMPLE.com ",
        security=SmtpSecurity.LOCAL,
        allow_local=True,
    )
    assert settings.sender == "sender@example.com"
    connection = MagicMock()
    connection.__enter__.return_value = connection
    with patch("api.auth.mail.smtplib.SMTP", return_value=connection):
        asyncio.run(
            AccountMailer(
                settings, AuthSettings("http://localhost:5173", True)
            ).send_link("owner@example.com", TokenPurpose.VERIFY, AccountToken.issue())
        )
    connection.send_message.assert_called_once()
    connection.starttls.assert_not_called()
    connection.login.assert_not_called()


@pytest.mark.parametrize(
    "host",
    ["smtp..example", "-smtp.example", "smtp.example/path", "a" * 64 + ".example"],
)
def test_invalid_smtp_host_is_rejected_at_configuration_ingress(host):
    with pytest.raises(ValidationError):
        SmtpSettings(host=host, port=587, sender="sender@example.com")
