"""In-memory mail sink for disposable tests; never mounted by the shipped API."""

import hashlib
import json

from api.auth.mail import ACCOUNT_MAILER_STATE_KEY
from api.auth.recovery.policy import TokenPurpose
from api.auth.recovery.tokens import AccountToken
from api.http.protocol import CACHE_CONTROL_HEADER, NO_STORE_CACHE_DIRECTIVE
from fastapi import status
from fastapi.responses import JSONResponse

TEST_MAILBOX_TTL_SECONDS = 120
MAILBOX_EMAIL_PARAMETER = "email"
MAILBOX_LINK_FIELD = "link"
MAILBOX_PATH = "/api/v1/__test/account-mail"


class MemoryAccountMailer:
    def __init__(self):
        self.messages = {}

    async def send_link(self, email, purpose, token):
        self.messages[email] = (purpose, token)


class SharedTestMailer:
    """Test-only mailbox shared across disposable acceptance API processes."""

    def __init__(self, app):
        self.app = app

    async def send_link(self, email, purpose, token):
        await self.app.state.redis.set(
            self.key(email),
            json.dumps([purpose, token.value]),
            ex=TEST_MAILBOX_TTL_SECONDS,
        )

    async def read(self, email):
        value = await self.app.state.redis.get(self.key(email))
        if value is None:
            return None
        purpose, token = json.loads(value)
        return TokenPurpose(purpose), AccountToken.parse(token)

    @staticmethod
    def key(email):
        return "polybot:test-mail:" + hashlib.sha256(email.encode()).hexdigest()


def install_browser_mailbox(app, origin):
    mailer = SharedTestMailer(app)
    setattr(app.state, ACCOUNT_MAILER_STATE_KEY, mailer)

    @app.middleware("http")
    async def test_mailbox(request, call_next):
        if request.url.path == MAILBOX_PATH:
            item = await mailer.read(
                request.query_params.get(MAILBOX_EMAIL_PARAMETER, "")
            )
            if item is None:
                return JSONResponse({}, status_code=status.HTTP_404_NOT_FOUND)
            purpose, token = item
            return JSONResponse(
                {MAILBOX_LINK_FIELD: purpose.email_link(origin, token.value)},
                headers={CACHE_CONTROL_HEADER: NO_STORE_CACHE_DIRECTIVE},
            )
        return await call_next(request)
