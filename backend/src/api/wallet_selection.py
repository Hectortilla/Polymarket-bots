"""Wallet selection constraints shared by HTTP and launch configuration."""

from typing import Annotated

from polybot.framework.wallets import (
    WALLET_ADDRESS_SCHEMA_PATTERN,
    validate_wallet_address,
)
from pydantic import AfterValidator, StringConstraints

from api.limits.policy import PAPER_BETA

type WalletAddress = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        pattern=WALLET_ADDRESS_SCHEMA_PATTERN,
    ),
    AfterValidator(validate_wallet_address),
]


MAX_SELECTED_WALLETS = PAPER_BETA.followed_wallets_per_run

MIN_SELECTED_WALLETS = 1
