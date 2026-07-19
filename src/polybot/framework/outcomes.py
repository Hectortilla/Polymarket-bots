from polybot.polymarket.markets import Market


def resolve_outcome_token(market: Market, outcome_label: str) -> str | None:
    return market.token_id_for_outcome(outcome_label)
