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
