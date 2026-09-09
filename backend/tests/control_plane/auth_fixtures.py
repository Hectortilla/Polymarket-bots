"""Explicit identities for pre-auth regression tests; isolation tests use real sessions."""

from time import monotonic
from unittest.mock import AsyncMock
from uuid import UUID

from api.auth.config import AuthSettings
from api.auth.contracts import CurrentUser
from api.auth.dependencies import CurrentUserDependency, application_authentication
from api.auth.models import UserRow
from api.auth.store.tokens import SessionToken
from api.http.app import create_app
from api.http.dependencies import SessionFactoryDependency
from api.http.protocol import CONTENT_TYPE_HEADER, JSON_CONTENT_TYPE
from api.http.routes.run_lookup import require_stored_run
from api.limits.http import application_resource_limits, stream_lease
from api.limits.policy import STREAM_LIFETIME_SECONDS
from api.limits.redis.stream_admission import StreamLease
from fastapi import Request
from fastapi.testclient import TestClient
from polybot.framework.clock import system_now_utc
from sqlalchemy.dialects.postgresql import insert

TEST_USER_ID = UUID("144d7847-c130-44c9-b8d9-663123a2e299")
TEST_ORIGIN = "http://test"
TEST_HEADERS = {"Origin": TEST_ORIGIN, CONTENT_TYPE_HEADER: JSON_CONTENT_TYPE}


async def ensure_test_user(session) -> UUID:
    await session.execute(
        insert(UserRow)
        .values(
            created_at=system_now_utc(),
            id=TEST_USER_ID,
            email="regression@example.com",
            password_hash="unused-in-trusted-regression-tests",
        )
        .on_conflict_do_nothing()
    )
    return TEST_USER_ID


async def regression_identity(request: Request) -> None:
    request.state.session_token = SessionToken.issue()
    request.state.user = CurrentUser(id=TEST_USER_ID, email="regression@example.com")


async def regression_stream_lease(
    run_id: UUID, session_factory: SessionFactoryDependency, user: CurrentUserDependency
):
    async with session_factory() as session:
        await require_stored_run(session, run_id, user.id)
    yield StreamLease(
        AsyncMock(),
        ("fixture-user", "fixture-global"),
        "fixture-token",
        monotonic() + STREAM_LIFETIME_SECONDS,
    )


def create_authenticated_app(**kwargs):
    application = create_app(
        auth_settings=AuthSettings(TEST_ORIGIN, allow_http=True), **kwargs
    )
    application.dependency_overrides[application_authentication] = regression_identity
    application.dependency_overrides[application_resource_limits] = lambda: None
    application.dependency_overrides[stream_lease] = regression_stream_lease
    return application


def authenticated_test_client(application, **kwargs):
    return TestClient(application, headers=TEST_HEADERS, **kwargs)
