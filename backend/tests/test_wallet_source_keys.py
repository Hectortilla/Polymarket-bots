import pytest
from polybot.framework.events.wallet_trades import (
    WALLET_SOURCE_KEY_FORBIDDEN_CHARACTER,
    WALLET_SOURCE_KEY_SEPARATOR,
    parse_wallet_source_key,
    wallet_source_key,
)


def test_source_id_can_contain_separator_without_losing_identity() -> None:
    source_id = f"transaction{WALLET_SOURCE_KEY_SEPARATOR}index"
    key = wallet_source_key("0xLeader", source_id)
    assert parse_wallet_source_key(key) == ("0xleader", source_id)
    assert WALLET_SOURCE_KEY_FORBIDDEN_CHARACTER not in key


@pytest.mark.parametrize(
    "wallet, source_id",
    [
        ("", "source"),
        (f"wallet{WALLET_SOURCE_KEY_SEPARATOR}suffix", "source"),
        (f"wallet{WALLET_SOURCE_KEY_FORBIDDEN_CHARACTER}", "source"),
        ("wallet", ""),
        ("wallet", f"source{WALLET_SOURCE_KEY_FORBIDDEN_CHARACTER}"),
    ],
)
def test_source_key_rejects_unrepresentable_components(
    wallet: str, source_id: str
) -> None:
    with pytest.raises(ValueError):
        wallet_source_key(wallet, source_id)


@pytest.mark.parametrize(
    "key",
    ["", "wallet", ":source", "wallet:", "wallet:\x00source", "wallet\x00:source"],
)
def test_parser_rejects_malformed_keys(key: str) -> None:
    assert parse_wallet_source_key(key) is None
