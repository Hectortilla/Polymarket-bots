"""Generate test-only browser route contracts separately from shipped UI assets."""

import json
from dataclasses import asdict
from pathlib import Path

from api.catalog.inputs import NodeBasedLaunchInputs
from polybot.framework.streams import (
    STREAM_RULE_MARKET_SLUGS_FIELD,
    STREAM_RULE_WALLET_ADDRESSES_FIELD,
)

from control_plane.account_mail_fixture import (
    MAILBOX_EMAIL_PARAMETER,
    MAILBOX_LINK_FIELD,
    MAILBOX_PATH,
)
from control_plane.browser_limits_fixture import CLEAR_LIMITS_PATH
from control_plane.browser_wallet_fixture import BROWSER_WALLET

ACCOUNT_BROWSER_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "frontend/e2e/accountContract.fixture.json"
)


def account_browser_contract():
    selector_fields = NodeBasedLaunchInputs.model_json_schema()["properties"]
    return {
        "wallet": asdict(BROWSER_WALLET),
        "selectorLabels": {
            "markets": selector_fields[STREAM_RULE_MARKET_SLUGS_FIELD]["title"],
            "wallets": selector_fields[STREAM_RULE_WALLET_ADDRESSES_FIELD]["title"],
        },
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
