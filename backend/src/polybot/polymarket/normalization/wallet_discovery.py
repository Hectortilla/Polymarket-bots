"""Translate public profiles into validated trading-wallet identities."""

from polybot.framework.wallets import validate_wallet_address
from polybot.polymarket.wallet_discovery_contracts import WalletSuggestion
from polymarket.models.gamma.profile import PublicProfile
from polymarket.models.gamma.search import Profile


def normalize_wallet_suggestion(source: Profile | PublicProfile) -> WalletSuggestion:
    if source.wallet is None:
        raise ValueError("profile has no trading wallet")
    address = validate_wallet_address(source.wallet)
    name = source.name if source.display_username_public is not False else None
    label = name or source.pseudonym
    if label is not None:
        if not isinstance(label, str):
            raise ValueError("profile label must be text")
        label = label.strip() or None
    return WalletSuggestion(address=address, name=label)
