from typing import Protocol


YES_OUTCOME = "Yes"
NO_OUTCOME = "No"


class OutcomeTokenLookup(Protocol):
    def token_id_for_outcome(self, outcome_label: str) -> str | None: ...


def resolve_outcome_token(
    market: OutcomeTokenLookup,
    outcome_label: str,
) -> str | None:
    return market.token_id_for_outcome(outcome_label)
