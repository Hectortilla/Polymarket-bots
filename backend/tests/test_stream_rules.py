import pytest
from polybot.framework.streams import StreamPlan, StreamRelation, StreamRule


def test_mixed_rules_union_their_trade_relations() -> None:
    plan = StreamPlan(
        current=(
            StreamRule(
                StreamRelation.FILTERED,
                market_slugs=("btc",),
                wallet_addresses=("0xleader",),
            ),
            StreamRule(
                StreamRelation.INDEPENDENT,
                market_slugs=("eth",),
                wallet_addresses=("0xglobal",),
            ),
        )
    )

    assert plan.accepts_trade("0xleader", "btc")
    assert plan.accepts_trade("0xother", "eth")
    assert not plan.accepts_trade("0xleader", "sol")
    assert plan.accepts_trade("0xglobal", None)


@pytest.mark.parametrize(
    ("relation", "markets", "wallets"),
    (
        (StreamRelation.FILTERED, (), ("wallet",)),
        (StreamRelation.FILTERED, ("market",), ()),
        (StreamRelation.INDEPENDENT, (), ()),
    ),
)
def test_rules_require_their_selector_groups(relation, markets, wallets):
    with pytest.raises(ValueError, match="stream rules require"):
        StreamRule(relation, markets, wallets)


def test_filtered_market_scopes_union_for_one_wallet():
    plan = StreamPlan(
        current=(
            StreamRule(StreamRelation.FILTERED, ("first",), ("wallet",)),
            StreamRule(StreamRelation.FILTERED, ("second",), ("wallet",)),
        )
    )
    assert plan.wallet_discovery_scopes() == {"wallet": frozenset({"first", "second"})}
    assert plan.accepts_trade("wallet", "first")
    assert plan.accepts_trade("wallet", "second")
    assert not plan.accepts_trade("wallet", "third")
