"""Credential/config ingress and fail-closed adapter regressions."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from api.auth.config import AUTH_ALLOW_HTTP_ENV, AUTH_ORIGIN_ENV, AuthSettings
from api.auth.contracts import LogoutResponse
from api.auth.middleware.body import AuthRequestBody
from api.auth.passwords import PasswordVerificationError, verify_password
from api.auth.policy import AUTH_BODY_MAX_BYTES
from api.auth.store.tokens import SESSION_TOKEN_LENGTH, SessionToken
from api.auth.token_digest import AUTH_TOKEN_DIGEST_HEX_LENGTH
from api.http.app import create_app
from api.http.dependencies import application_lifespan
from fastapi import HTTPException, status

from control_plane.disposable_services import (
    disposable_postgres_url,
    disposable_redis_url,
)


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.com:garbage",
        "https://example.com:99999",
        "https://example.com:",
        "https://example.com/path",
        "https://user@example.com",
        "https://@example.com",
        " https://example.com",
        "https://exam ple.com",
        "https://exa_mple.com",
        "https://example.com?query=1",
    ],
)
def test_invalid_auth_origin_is_rejected(origin):
    with pytest.raises(ValueError):
        AuthSettings(origin)


@pytest.mark.parametrize(
    ("origin", "canonical"),
    [
        ("HTTPS://PAPER.EXAMPLE.COM:443", "https://paper.example.com"),
        ("https://[0:0:0:0:0:0:0:1]:8443", "https://[::1]:8443"),
    ],
)
def test_https_origin_is_canonical_and_cookies_stay_secure(origin, canonical):
    settings = AuthSettings(origin)
    assert settings.origin == canonical
    assert settings.secure_cookie


@pytest.mark.parametrize("invalid_flag", [None, "yes"])
def test_invalid_auth_environment_prevents_application_startup(
    monkeypatch, invalid_flag
):
    monkeypatch.delenv(AUTH_ORIGIN_ENV, raising=False)
    if invalid_flag is not None:
        monkeypatch.setenv(AUTH_ORIGIN_ENV, "https://paper.example.com")
        monkeypatch.setenv(AUTH_ALLOW_HTTP_ENV, invalid_flag)

    async def start():
        async with application_lifespan(create_app()):
            pytest.fail("invalid auth configuration must prevent startup")

    with pytest.raises(ValueError):
        asyncio.run(start())


def test_session_token_generation_and_ingress_share_the_policy():
    token = SessionToken.issue()
    assert len(token.value) == SESSION_TOKEN_LENGTH
    assert len(token.digest) == AUTH_TOKEN_DIGEST_HEX_LENGTH
    assert SessionToken.parse(token.value) == token
    assert token.value not in repr(token)
    for malformed in (None, "", "!" * SESSION_TOKEN_LENGTH, token.value + "x"):
        assert SessionToken.parse(malformed) is None


def test_logout_contract_requires_an_exact_success_response():
    assert LogoutResponse(logged_out=True).model_dump() == {"logged_out": True}
    for value in ({}, {"logged_out": False}, {"logged_out": True, "extra": "secret"}):
        with pytest.raises(ValueError):
            LogoutResponse.model_validate(value)


def test_malformed_persisted_password_hash_has_a_domain_failure():
    with pytest.raises(PasswordVerificationError, match="verification unavailable"):
        asyncio.run(verify_password("invalid persisted hash", "password"))


def test_auth_body_replays_once_then_preserves_disconnect():
    async def scenario():
        receive = AsyncMock(
            side_effect=[
                {"type": "http.request", "body": b"first", "more_body": True},
                {"type": "http.request", "body": b"second", "more_body": False},
                {"type": "http.disconnect"},
            ]
        )
        body = await AuthRequestBody.read(receive)
        assert body is not None
        assert await body.receive() == {
            "type": "http.request",
            "body": b"firstsecond",
            "more_body": False,
        }
        assert await body.receive() == {"type": "http.disconnect"}

    asyncio.run(scenario())


def test_auth_body_rejects_chunked_overflow():
    receive = AsyncMock(
        side_effect=[
            {
                "type": "http.request",
                "body": b"x" * AUTH_BODY_MAX_BYTES,
                "more_body": True,
            },
            {"type": "http.request", "body": b"x", "more_body": False},
        ]
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(AuthRequestBody.read(receive))
    assert raised.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE


@pytest.mark.parametrize(
    "url",
    [
        "redis://remote.example:6379/1",
        "redis://127.0.0.1:6379/0",
        "redis://127.0.0.1:6379",
        "redis://127.0.0.1:6379/1?db=0",
    ],
)
def test_disposable_redis_boundary_rejects_unsafe_targets(url):
    with pytest.raises(ValueError):
        disposable_redis_url(url)


def test_disposable_services_accept_only_explicit_local_test_targets():
    redis_url = "redis://127.0.0.1:56379/14"
    assert disposable_redis_url(redis_url) == redis_url
    assert (
        disposable_postgres_url("postgresql://127.0.0.1/example_test").database
        == "example_test"
    )
    with pytest.raises(ValueError):
        disposable_postgres_url("postgresql://127.0.0.1/accounts")
