"""Account policy documentation and test-only browser contracts stay synchronized."""

import json
from pathlib import Path

from api.auth.mail.config import (
    SMTP_FROM_ENV,
    SMTP_HOST_ENV,
    SMTP_PASSWORD_ENV,
    SMTP_PORT_ENV,
    SMTP_SECURITY_ENV,
    SMTP_TIMEOUT_SECONDS,
    SMTP_USERNAME_ENV,
    SmtpSecurity,
)
from api.auth.policy import AUTH_RATE_WINDOW_SECONDS, SESSION_RECHECK_SECONDS
from api.auth.recovery.policy import (
    ACCOUNT_TOKEN_ENTROPY_BYTES,
    CREDENTIAL_ATTEMPT_LIMIT,
    EMAIL_ATTEMPT_LIMIT,
    MAIL_RESPONSE_MIN_SECONDS,
    TOKEN_LIFETIME_SECONDS,
)

from control_plane.account_browser_contract import (
    ACCOUNT_BROWSER_CONTRACT_PATH,
    account_browser_contract,
)
from control_plane.account_mail_fixture import TEST_MAILBOX_TTL_SECONDS

ROOT = Path(__file__).resolve().parents[3]


def test_account_browser_fixture_matches_owners():
    assert (
        json.loads(ACCOUNT_BROWSER_CONTRACT_PATH.read_text())
        == account_browser_contract()
    )


def test_account_policy_runbook_matches_runtime():
    runbook = (ROOT / "docs/account-recovery.md").read_text()
    for label, value in (
        ("Token entropy (bytes)", ACCOUNT_TOKEN_ENTROPY_BYTES),
        ("Token lifetime (seconds)", TOKEN_LIFETIME_SECONDS),
        ("Attempt window (seconds)", AUTH_RATE_WINDOW_SECONDS),
        ("Attempts per endpoint/IP", CREDENTIAL_ATTEMPT_LIMIT),
        ("Mail attempts per email", EMAIL_ATTEMPT_LIMIT),
        ("Minimum mail response (seconds)", MAIL_RESPONSE_MIN_SECONDS),
        ("SMTP socket timeout (seconds)", SMTP_TIMEOUT_SECONDS),
        ("Test mailbox retention (seconds)", TEST_MAILBOX_TTL_SECONDS),
        ("Session recheck interval (seconds)", SESSION_RECHECK_SECONDS),
    ):
        assert f"| {label} | {value:g} |" in runbook


def test_smtp_configuration_names_match_deployment_and_runbook():
    for relative_path in (
        "deploy/compose.yaml",
        "deploy/release.env.example",
        "docs/account-recovery.md",
    ):
        contents = (ROOT / relative_path).read_text()
        for name in (SMTP_HOST_ENV, SMTP_PORT_ENV, SMTP_SECURITY_ENV, SMTP_FROM_ENV):
            assert name in contents, (relative_path, name)


def test_smtp_secret_file_names_match_deployment_and_runbook():
    for relative_path in ("deploy/compose.yaml", "docs/account-recovery.md"):
        contents = (ROOT / relative_path).read_text()
        for name in (SMTP_USERNAME_ENV, SMTP_PASSWORD_ENV):
            assert name + "_FILE" in contents, (relative_path, name)


def test_smtp_security_values_match_runbook_and_deployment_default():
    runbook = (ROOT / "docs/account-recovery.md").read_text()
    assert f"| SMTP security values | {', '.join(SmtpSecurity)} |" in runbook
    for security in SmtpSecurity:
        assert f"`{security}`" in runbook
    compose = (ROOT / "deploy/compose.yaml").read_text()
    assert (
        f"{SMTP_SECURITY_ENV}: ${{{SMTP_SECURITY_ENV}:-{SmtpSecurity.STARTTLS}}}"
        in compose
    )
    for relative_path in ("docs/account-recovery.md", "deploy/release.env.example"):
        assert (
            f"{SMTP_SECURITY_ENV}={SmtpSecurity.STARTTLS}"
            in (ROOT / relative_path).read_text()
        )
