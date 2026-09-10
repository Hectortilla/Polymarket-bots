"""Account-link and reauthentication policy; no transport or ORM dependencies."""

from enum import StrEnum


class TokenPurpose(StrEnum):
    RESET = "reset"
    VERIFY = "verify"

    @property
    def verifies_email(self) -> bool:
        return self is TokenPurpose.VERIFY

    def email_link(self, origin: str, token_value: str) -> str:
        return f"{origin}{ACCOUNT_LINK_PATHS[self]}#{token_value}"


class SessionRevocation(StrEnum):
    OTHER = "other"
    ALL = "all"

    @property
    def revokes_current(self) -> bool:
        return self is SessionRevocation.ALL


ACCOUNT_TOKEN_ENTROPY_BYTES = 32
TOKEN_LIFETIME_MINUTES = 30
TOKEN_LIFETIME_SECONDS = TOKEN_LIFETIME_MINUTES * 60
CREDENTIAL_ATTEMPT_LIMIT = 5
EMAIL_ATTEMPT_LIMIT = 3
ACCOUNT_PATH = "/auth/account"
RESET_REQUEST_PATH = "/auth/password/reset/request"
RESET_COMPLETE_PATH = "/auth/password/reset/complete"
VERIFY_REQUEST_PATH = "/auth/email/verification/request"
VERIFY_COMPLETE_PATH = "/auth/email/verification/complete"
PASSWORD_CHANGE_PATH = "/auth/password/change"
SESSIONS_REVOKE_PATH = "/auth/sessions/revoke"
MAIL_REQUEST_PATHS = (RESET_REQUEST_PATH, VERIFY_REQUEST_PATH)
PUBLIC_RECOVERY_PATHS = (*MAIL_REQUEST_PATHS, RESET_COMPLETE_PATH, VERIFY_COMPLETE_PATH)
CREDENTIAL_PATHS = (*PUBLIC_RECOVERY_PATHS, PASSWORD_CHANGE_PATH, SESSIONS_REVOKE_PATH)
BROWSER_RESET_PATH = "/reset-password"
BROWSER_VERIFY_PATH = "/verify-email"
BROWSER_ACCOUNT_PATH = "/account"
BROWSER_FORGOT_PATH = "/forgot-password"
TOKEN_INVALID_DETAIL = (
    "This link is invalid, expired or already used. Request a new link."
)
REAUTHENTICATION_FAILED_DETAIL = (
    "Current password or session is invalid. Sign in and try again."
)
VERIFICATION_REQUIRED_DETAIL = (
    "Verify your email in Account settings before launching a run."
)

ACCOUNT_LINK_PATHS = {
    TokenPurpose.RESET: BROWSER_RESET_PATH,
    TokenPurpose.VERIFY: BROWSER_VERIFY_PATH,
}
ACCOUNT_EMAIL_RATE_LIMIT_SCOPE = "account-email"
MAIL_RESPONSE_MIN_SECONDS = 1.0
ACCOUNT_STATUS_OPERATION_ID = "accountStatus"
RESET_REQUEST_OPERATION_ID = "requestPasswordReset"
RESET_COMPLETE_OPERATION_ID = "completePasswordReset"
VERIFY_REQUEST_OPERATION_ID = "requestEmailVerification"
VERIFY_COMPLETE_OPERATION_ID = "completeEmailVerification"
PASSWORD_CHANGE_OPERATION_ID = "changePassword"
SESSIONS_REVOKE_OPERATION_ID = "revokeSessions"
