"""Only the reauthenticated session owner can request account erasure."""

import asyncio
from uuid import UUID

from api.auth.models import UserRow
from api.auth.policy import LOGIN_PATH, ME_PATH
from api.http.routes.paths import api_route_path
from api.lifecycle.deletion.models import DeletionRequestRow
from api.lifecycle.http import ACCOUNT_DELETION_PATH
from fastapi import status
from httpx import ASGITransport, AsyncClient

from control_plane.test_auth import HEADERS, ORIGIN, PASSWORD, run_scenario, signup
from control_plane.test_auth import services as services


def test_deletion_requires_password_rejects_target_injection_and_revokes_access(
    services,
):
    async def scenario(client, app, factory, redis, launcher):
        owner = (await signup(client)).json()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers=HEADERS
        ) as other:
            other_user = (await signup(other, "other-deletion@example.com")).json()
            path = api_route_path(ACCOUNT_DELETION_PATH)
            assert (
                await client.post(path, json={"current_password": "incorrect password"})
            ).status_code == status.HTTP_403_FORBIDDEN
            assert (
                await client.post(
                    path,
                    json={"current_password": PASSWORD, "user_id": other_user["id"]},
                )
            ).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
            async with factory() as session:
                assert await session.get(DeletionRequestRow, UUID(owner["id"])) is None
            response = await client.post(path, json={"current_password": PASSWORD})
            assert response.status_code == status.HTTP_202_ACCEPTED
            assert "Max-Age=0" in response.headers["set-cookie"]
            assert (
                await client.get(api_route_path(ME_PATH))
            ).status_code == status.HTTP_401_UNAUTHORIZED
            assert (
                await client.post(
                    api_route_path(LOGIN_PATH),
                    json={"email": owner["email"], "password": PASSWORD},
                )
            ).status_code == status.HTTP_401_UNAUTHORIZED
            assert (await other.get(api_route_path(ME_PATH))).json()[
                "id"
            ] == other_user["id"]
            async with factory() as session:
                assert (
                    await session.get(UserRow, UUID(owner["id"]))
                ).suspended_at is not None
                assert (
                    await session.get(DeletionRequestRow, UUID(other_user["id"]))
                    is None
                )

    asyncio.run(run_scenario(services, scenario))
