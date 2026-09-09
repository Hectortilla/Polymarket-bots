"""Recovery acceptance against real PostgreSQL and Redis; mail stays in memory."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID

import api.auth.routes as auth_routes
import pytest
from api.auth.mail import MailDeliveryError
from api.auth.models import SessionRow, UserRow
from api.auth.passwords import HASHER
from api.auth.policy import LOGIN_PATH, ME_PATH, SESSION_COOKIE, SESSION_RECHECK_SECONDS
from api.auth.recovery.contracts import AccountActionResponse, AccountStatus
from api.auth.recovery.models import AccountTokenRow
from api.auth.recovery.policy import (
    ACCOUNT_PATH,
    CREDENTIAL_PATHS,
    EMAIL_ATTEMPT_LIMIT,
    MAIL_RESPONSE_MIN_SECONDS,
    PASSWORD_CHANGE_PATH,
    RESET_COMPLETE_PATH,
    RESET_REQUEST_PATH,
    SESSIONS_REVOKE_PATH,
    TOKEN_INVALID_DETAIL,
    VERIFICATION_REQUIRED_DETAIL,
    VERIFY_COMPLETE_PATH,
    VERIFY_REQUEST_PATH,
    SessionRevocation,
    TokenPurpose,
)
from api.auth.store.tokens import SessionToken
from api.auth.streams import StreamAuthorization
from api.catalog.definitions import WINNER_DEFINITION_ID
from api.http.routes.paths import (
    BOT_RUNS_PATH,
    BOTS_PATH,
    RUN_PATH,
    RUN_STOP_PATH,
    api_route_path,
)
from api.runs.status import RunStatus
from fastapi import status
from httpx import ASGITransport, AsyncClient
from polybot.framework.clock import system_now_utc
from sqlalchemy import func, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from control_plane.account_mail_fixture import MemoryAccountMailer
from control_plane.disposable_services import clear_auth_attempts
from control_plane.test_auth import HEADERS, ORIGIN, PASSWORD, run_scenario, signup
from control_plane.test_auth import services as services

NEW_PASSWORD = "new account recovery password"


async def request_link(client, app, email, purpose=TokenPurpose.RESET):
    if not hasattr(app.state, "account_mailer"):
        app.state.account_mailer = MemoryAccountMailer()
    path = RESET_REQUEST_PATH if purpose is TokenPurpose.RESET else VERIFY_REQUEST_PATH
    response = await client.post(api_route_path(path), json={"email": email})
    assert response.status_code == status.HTTP_200_OK
    return app.state.account_mailer.messages[email][1]


async def redeem(client, token, purpose=TokenPurpose.RESET, password=NEW_PASSWORD):
    path = (
        RESET_COMPLETE_PATH if purpose is TokenPurpose.RESET else VERIFY_COMPLETE_PATH
    )
    return await client.post(
        api_route_path(path), json={"token": token.value, "new_password": password}
    )


async def login(client, email, password=NEW_PASSWORD):
    return await client.post(
        api_route_path(LOGIN_PATH), json={"email": email, "password": password}
    )


def test_reset_revokes_all_access_and_preserves_other_accounts(services):
    async def scenario(client, app, factory, redis, launcher):
        owner = (await signup(client)).json()
        old_token = SessionToken.parse(client.cookies.get(SESSION_COOKIE))
        authorization = StreamAuthorization(factory, old_token, UUID(owner["id"]))
        with patch("api.auth.streams.monotonic", return_value=0):
            assert await authorization.allowed()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers=HEADERS
        ) as other:
            other_user = (await signup(other, "other@example.com")).json()
            token = await request_link(client, app, owner["email"])
            response = await redeem(client, token)
            assert response.status_code == status.HTTP_200_OK
            assert response.json() == AccountActionResponse(accepted=True).model_dump()
            assert (
                token.value not in response.text and NEW_PASSWORD not in response.text
            )
            assert (await other.get(api_route_path(ME_PATH))).json()[
                "id"
            ] == other_user["id"]
            assert (
                await login(other, owner["email"], PASSWORD)
            ).status_code == status.HTTP_401_UNAUTHORIZED
        assert (
            await client.get(api_route_path(ME_PATH))
        ).status_code == status.HTTP_401_UNAUTHORIZED
        with patch("api.auth.streams.monotonic", return_value=SESSION_RECHECK_SECONDS):
            assert not await authorization.allowed()
        assert (await redeem(client, token)).status_code == status.HTTP_400_BAD_REQUEST
        assert (await login(client, owner["email"])).status_code == status.HTTP_200_OK
        async with factory() as session:
            user = await session.get(UserRow, UUID(owner["id"]))
            assert user.email_verified_at is None
            assert HASHER.verify(user.password_hash, NEW_PASSWORD)
            assert (
                await session.scalar(select(func.count()).select_from(AccountTokenRow))
                == 0
            )

    asyncio.run(run_scenario(services, scenario))


def test_expiry_wrong_purpose_resend_and_concurrent_redemption(services):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        first = await request_link(client, app, email)
        second = await request_link(client, app, email)
        assert (await redeem(client, first)).status_code == status.HTTP_400_BAD_REQUEST
        assert (
            await redeem(client, second, TokenPurpose.VERIFY)
        ).status_code == status.HTTP_400_BAD_REQUEST
        async with factory() as session:
            await session.execute(
                update(AccountTokenRow).values(
                    expires_at=system_now_utc() - timedelta(seconds=1)
                )
            )
            await session.commit()
        assert (await redeem(client, second)).json()["detail"] == TOKEN_INVALID_DETAIL
        token = await request_link(client, app, email)
        responses = await asyncio.gather(redeem(client, token), redeem(client, token))
        assert sorted(item.status_code for item in responses) == [
            status.HTTP_200_OK,
            status.HTTP_400_BAD_REQUEST,
        ]

    asyncio.run(run_scenario(services, scenario))


def test_link_requests_have_equal_discovery_and_delivery_failure_responses(services):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        app.state.account_mailer = MemoryAccountMailer()
        for path in (RESET_REQUEST_PATH, VERIFY_REQUEST_PATH):
            responses = [
                await client.post(api_route_path(path), json={"email": address})
                for address in (email, "unknown@example.com")
            ]
            assert (
                responses[0].status_code
                == responses[1].status_code
                == status.HTTP_200_OK
            )
            assert responses[0].json() == responses[1].json()
            assert (
                await redeem(
                    client, app.state.account_mailer.messages["unknown@example.com"][1]
                )
            ).status_code == status.HTTP_400_BAD_REQUEST
        await clear_auth_attempts(redis)
        app.state.account_mailer = AsyncMock()
        app.state.account_mailer.send_link.side_effect = MailDeliveryError(
            "secret SMTP failure"
        )
        responses = [
            await client.post(
                api_route_path(RESET_REQUEST_PATH), json={"email": address}
            )
            for address in (email, "unknown@example.com")
        ]
        assert (
            responses[0].status_code
            == responses[1].status_code
            == status.HTTP_503_SERVICE_UNAVAILABLE
        )
        assert responses[0].json() == responses[1].json()
        assert "secret" not in responses[0].text
        async with factory() as session:
            user = (await session.execute(select(UserRow))).scalar_one()
            assert HASHER.verify(user.password_hash, PASSWORD)

    asyncio.run(run_scenario(services, scenario))


def test_email_budget_is_shared_across_purposes_and_client_addresses(services):
    async def scenario(client, app, factory, redis, launcher):
        app.state.account_mailer = MemoryAccountMailer()
        for index in range(EMAIL_ATTEMPT_LIMIT + 1):
            async with AsyncClient(
                transport=ASGITransport(app=app, client=(f"127.0.0.{index + 1}", 1234)),
                base_url=ORIGIN,
                headers=HEADERS,
            ) as peer:
                path = RESET_REQUEST_PATH if index % 2 else VERIFY_REQUEST_PATH
                response = await peer.post(
                    api_route_path(path), json={"email": " UNKNOWN@example.com "}
                )
                assert response.status_code == (
                    status.HTTP_429_TOO_MANY_REQUESTS
                    if index == EMAIL_ATTEMPT_LIMIT
                    else status.HTTP_200_OK
                )

    asyncio.run(run_scenario(services, scenario))


def test_verification_gates_launch_and_revocation_does_not_stop_paper_run(services):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        account = (await client.get(api_route_path(ACCOUNT_PATH))).json()
        assert (
            account
            == AccountStatus(
                email_verified=False, verification_required=True
            ).model_dump()
        )
        bot_response = await client.post(
            api_route_path(BOTS_PATH),
            json={
                "definition_id": WINNER_DEFINITION_ID,
                "inputs": {"name": "verified launch"},
            },
        )
        assert bot_response.status_code == status.HTTP_201_CREATED, bot_response.text
        bot = bot_response.json()
        denied = await client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"]))
        assert denied.status_code == status.HTTP_403_FORBIDDEN
        assert denied.json()["detail"] == VERIFICATION_REQUIRED_DETAIL
        launcher.launch.assert_not_called()
        token = await request_link(client, app, email, TokenPurpose.VERIFY)
        assert (
            await redeem(client, token, TokenPurpose.VERIFY)
        ).status_code == status.HTTP_200_OK
        assert (await login(client, email)).status_code == status.HTTP_200_OK
        assert (await client.get(api_route_path(ACCOUNT_PATH))).json()[
            "email_verified"
        ] is True
        run_response = await client.post(
            api_route_path(BOT_RUNS_PATH, bot_id=bot["id"])
        )
        assert run_response.status_code == status.HTTP_202_ACCEPTED, run_response.text
        run = run_response.json()
        changed = await client.post(
            api_route_path(PASSWORD_CHANGE_PATH),
            json={"current_password": NEW_PASSWORD, "new_password": PASSWORD},
        )
        assert changed.status_code == status.HTTP_200_OK
        assert (await login(client, email, PASSWORD)).status_code == status.HTTP_200_OK
        assert (await client.get(api_route_path(RUN_PATH, run_id=run["id"]))).json()[
            "status"
        ] == RunStatus.QUEUED
        assert (
            await client.post(api_route_path(RUN_STOP_PATH, run_id=run["id"]))
        ).status_code == status.HTTP_200_OK

    asyncio.run(run_scenario(services, scenario))


def test_reauthentication_and_other_all_session_revocation(services):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers=HEADERS
        ) as peer:
            await login(peer, email, PASSWORD)
            wrong = {
                "current_password": "incorrect password long enough",
                "scope": SessionRevocation.ALL,
            }
            assert (
                await client.post(api_route_path(SESSIONS_REVOKE_PATH), json=wrong)
            ).status_code == status.HTTP_403_FORBIDDEN
            assert (
                await peer.get(api_route_path(ME_PATH))
            ).status_code == status.HTTP_200_OK
            assert (
                await client.post(
                    api_route_path(SESSIONS_REVOKE_PATH),
                    json={
                        "current_password": PASSWORD,
                        "scope": SessionRevocation.OTHER,
                    },
                )
            ).status_code == status.HTTP_200_OK
            assert (
                await peer.get(api_route_path(ME_PATH))
            ).status_code == status.HTTP_401_UNAUTHORIZED
            assert (
                await client.get(api_route_path(ME_PATH))
            ).status_code == status.HTTP_200_OK
            assert (
                await client.post(
                    api_route_path(SESSIONS_REVOKE_PATH),
                    json={"current_password": PASSWORD, "scope": SessionRevocation.ALL},
                )
            ).status_code == status.HTTP_200_OK
            assert (
                await client.get(api_route_path(ME_PATH))
            ).status_code == status.HTTP_401_UNAUTHORIZED

    asyncio.run(run_scenario(services, scenario))


def test_reset_waits_for_login_and_revokes_its_committed_session(services):
    async def scenario(client, app, factory, redis, launcher):
        user = (await signup(client)).json()
        token = await request_link(client, app, user["email"])
        entered = asyncio.Event()
        release = asyncio.Event()
        original = auth_routes.verify_password

        async def paused_verify(*args):
            entered.set()
            await release.wait()
            return await original(*args)

        with patch("api.auth.routes.verify_password", side_effect=paused_verify):
            pending_login = asyncio.create_task(login(client, user["email"], PASSWORD))
            await entered.wait()
            pending_reset = asyncio.create_task(redeem(client, token))
            await asyncio.sleep(0.05)
            assert not pending_reset.done()
            release.set()
            assert (await pending_login).status_code == status.HTTP_200_OK
            assert (await pending_reset).status_code == status.HTTP_200_OK
        async with factory() as session:
            assert (
                await session.scalar(select(func.count()).select_from(SessionRow)) == 0
            )

    asyncio.run(run_scenario(services, scenario))


@pytest.mark.parametrize("path", CREDENTIAL_PATHS)
def test_recovery_ingress_never_echoes_secrets(services, path):
    async def scenario(client, app, factory, redis, launcher):
        await signup(client)
        secret = "secret payload that must not appear"
        response = await client.post(
            api_route_path(path),
            json={"token": secret, "new_password": secret, "current_password": secret},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert secret not in response.text
        response = await client.post(
            api_route_path(path), json={}, headers={"Origin": "https://foreign.example"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    asyncio.run(run_scenario(services, scenario))


def test_verification_removes_preregistration_credentials_and_cannot_be_repeated(
    services,
):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        stale_cookie = client.cookies.get(SESSION_COOKIE)
        token = await request_link(client, app, email, TokenPurpose.VERIFY)
        assert (
            await redeem(client, token, TokenPurpose.VERIFY)
        ).status_code == status.HTTP_200_OK
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=ORIGIN,
            headers=HEADERS,
            cookies={SESSION_COOKIE: stale_cookie},
        ) as stale:
            assert (
                await stale.get(api_route_path(ME_PATH))
            ).status_code == status.HTTP_401_UNAUTHORIZED
            assert (
                await login(stale, email, PASSWORD)
            ).status_code == status.HTTP_401_UNAUTHORIZED
        assert (await login(client, email)).status_code == status.HTTP_200_OK
        unused = await request_link(client, app, email, TokenPurpose.VERIFY)
        assert (
            await redeem(client, unused, TokenPurpose.VERIFY, PASSWORD)
        ).status_code == status.HTTP_400_BAD_REQUEST
        assert (await client.get(api_route_path(ACCOUNT_PATH))).json()[
            "email_verified"
        ] is True
        assert (await login(client, email)).status_code == status.HTTP_200_OK

    asyncio.run(run_scenario(services, scenario))


def test_wrong_current_password_cannot_change_credentials_or_sessions(services):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        response = await client.post(
            api_route_path(PASSWORD_CHANGE_PATH),
            json={
                "current_password": "wrong current password supplied",
                "new_password": NEW_PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert (
            await client.get(api_route_path(ME_PATH))
        ).status_code == status.HTTP_200_OK
        assert (
            await login(client, email, NEW_PASSWORD)
        ).status_code == status.HTTP_401_UNAUTHORIZED
        assert (await login(client, email, PASSWORD)).status_code == status.HTTP_200_OK

    asyncio.run(run_scenario(services, scenario))


def test_failed_verification_commit_rolls_back_password_proof_tokens_and_sessions(
    services,
):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        token = await request_link(client, app, email, TokenPurpose.VERIFY)
        with patch.object(
            AsyncSession,
            "commit",
            side_effect=OperationalError("forced", {}, Exception("private failure")),
        ):
            failed = await redeem(client, token, TokenPurpose.VERIFY)
        assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "private failure" not in failed.text
        assert (
            await client.get(api_route_path(ME_PATH))
        ).status_code == status.HTTP_200_OK
        async with factory() as session:
            user = (await session.execute(select(UserRow))).scalar_one()
            assert user.email_verified_at is None
            assert HASHER.verify(user.password_hash, PASSWORD)
            assert (
                await session.scalar(select(func.count()).select_from(AccountTokenRow))
                == 1
            )
        assert (
            await redeem(client, token, TokenPurpose.VERIFY)
        ).status_code == status.HTTP_200_OK

    asyncio.run(run_scenario(services, scenario))


@pytest.mark.parametrize("elapsed", [0.1, MAIL_RESPONSE_MIN_SECONDS + 1])
def test_mail_response_floor_covers_known_and_unknown_addresses(services, elapsed):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        app.state.account_mailer = MemoryAccountMailer()
        for address in (email, "absent@example.com"):
            with (
                patch("api.auth.recovery.http.monotonic", side_effect=[0, elapsed]),
                patch(
                    "api.auth.recovery.http.asyncio.sleep", new_callable=AsyncMock
                ) as delay,
            ):
                response = await client.post(
                    api_route_path(RESET_REQUEST_PATH), json={"email": address}
                )
                assert response.status_code == status.HTTP_200_OK
                delay.assert_awaited_once_with(
                    max(0, MAIL_RESPONSE_MIN_SECONDS - elapsed)
                )

    asyncio.run(run_scenario(services, scenario))


@pytest.mark.parametrize("purpose", list(TokenPurpose))
def test_issued_account_tokens_persist_only_the_digest(services, purpose):
    async def scenario(client, app, factory, redis, launcher):
        email = (await signup(client)).json()["email"]
        token = await request_link(client, app, email, purpose)
        async with factory() as session:
            row = (await session.execute(select(AccountTokenRow))).scalar_one()
            assert row.token_digest == token.digest
            assert row.token_digest != token.value
            assert token.value not in str(row.model_dump())
            assert row.purpose is purpose

    asyncio.run(run_scenario(services, scenario))
