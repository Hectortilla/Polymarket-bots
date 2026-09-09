"""Production mail startup uses secret files and fails closed on bad configuration."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from api.auth.config import AuthSettings
from api.auth.mail import ACCOUNT_MAILER_STATE_KEY, AccountMailer
from api.auth.mail.config import (
    SMTP_FROM_ENV,
    SMTP_HOST_ENV,
    SMTP_PASSWORD_ENV,
    SMTP_PORT_ENV,
    SMTP_SECURITY_ENV,
    SMTP_USERNAME_ENV,
    MailConfigurationError,
    SmtpSecurity,
)
from api.deployment.settings import Environment, StartupSettings
from api.http.app import create_app
from api.http.dependencies import application_lifespan
from pydantic import SecretStr

from control_plane.account_mail_fixture import MemoryAccountMailer
from control_plane.market_fixtures import market_discovery


def production_app():
    app = create_app(
        auth_settings=AuthSettings("https://paper.example.com"),
        session_factory=AsyncMock(),
        redis=AsyncMock(),
        launcher=AsyncMock(),
        market_discovery=market_discovery(),
    )
    app.state.startup_settings = StartupSettings(
        database_url=SecretStr("postgresql://unused"),
        redis_url=SecretStr("redis://unused"),
        environment=Environment.PRODUCTION,
        release_id="a" * 40,
        proxy_address="127.0.0.1",
    )
    return app


@pytest.fixture
def smtp_environment(monkeypatch, tmp_path):
    for name in (SMTP_USERNAME_ENV, SMTP_PASSWORD_ENV):
        monkeypatch.delenv(name, raising=False)
        secret = tmp_path / name
        secret.write_text("test SMTP credential")
        monkeypatch.setenv(name + "_FILE", str(secret))
    for name, value in {
        SMTP_HOST_ENV: "smtp.example.com",
        SMTP_PORT_ENV: "587",
        SMTP_FROM_ENV: "accounts@example.com",
        SMTP_SECURITY_ENV: SmtpSecurity.STARTTLS,
    }.items():
        monkeypatch.setenv(name, value)


def test_production_startup_loads_mailer_from_secret_files(smtp_environment):
    async def scenario():
        app = production_app()
        async with application_lifespan(app):
            assert isinstance(
                getattr(app.state, ACCOUNT_MAILER_STATE_KEY), AccountMailer
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("missing", [True, False])
def test_production_startup_refuses_missing_or_invalid_mail_configuration(
    smtp_environment, monkeypatch, missing
):
    if missing:
        monkeypatch.delenv(SMTP_HOST_ENV)
    else:
        monkeypatch.setenv(SMTP_HOST_ENV, "private malformed host")

    async def scenario():
        with pytest.raises(MailConfigurationError) as failure:
            async with application_lifespan(production_app()):
                pytest.fail("invalid mail configuration accepted")
        assert "private" not in str(failure.value)

    asyncio.run(scenario())


def test_installed_test_mailer_does_not_require_external_config(monkeypatch):
    monkeypatch.delenv(SMTP_HOST_ENV, raising=False)

    async def scenario():
        app = production_app()
        mailer = MemoryAccountMailer()
        setattr(app.state, ACCOUNT_MAILER_STATE_KEY, mailer)
        async with application_lifespan(app):
            assert getattr(app.state, ACCOUNT_MAILER_STATE_KEY) is mailer

    asyncio.run(scenario())


@pytest.mark.parametrize("missing", [SMTP_USERNAME_ENV, SMTP_PASSWORD_ENV])
def test_production_startup_refuses_one_sided_smtp_credentials(
    smtp_environment, monkeypatch, missing
):
    monkeypatch.delenv(missing + "_FILE")

    async def scenario():
        with pytest.raises(MailConfigurationError) as failure:
            async with application_lifespan(production_app()):
                pytest.fail("one-sided SMTP credential accepted")
        assert "test SMTP credential" not in str(failure.value)

    asyncio.run(scenario())
