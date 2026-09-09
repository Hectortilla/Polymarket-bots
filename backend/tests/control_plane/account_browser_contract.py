"""Generate test-only browser route contracts separately from shipped UI assets."""

import json
from pathlib import Path

from control_plane.account_mail_fixture import (
    MAILBOX_EMAIL_PARAMETER,
    MAILBOX_LINK_FIELD,
    MAILBOX_PATH,
)
from control_plane.browser_limits_fixture import CLEAR_LIMITS_PATH

ACCOUNT_BROWSER_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "frontend/e2e/accountContract.fixture.json"
)


def account_browser_contract():
    return {
        "mailboxPath": MAILBOX_PATH,
        "clearLimitsPath": CLEAR_LIMITS_PATH,
        "mailboxEmailParameter": MAILBOX_EMAIL_PARAMETER,
        "mailboxLinkField": MAILBOX_LINK_FIELD,
    }


def write_account_browser_contract():
    ACCOUNT_BROWSER_CONTRACT_PATH.write_text(
        json.dumps(account_browser_contract(), indent=2) + "\n"
    )


if __name__ == "__main__":
    write_account_browser_contract()
