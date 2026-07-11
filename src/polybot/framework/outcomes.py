from polybot.polymarket.types import Market, token_id_for_outcome


def resolve_outcome_token(market: Market, outcome_label: str) -> str | None:
    return token_id_for_outcome(market, outcome_label)
