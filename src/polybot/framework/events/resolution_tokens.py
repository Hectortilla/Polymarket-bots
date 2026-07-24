"""Binary-market token topology shared by resolution contracts."""


def normalize_resolution_tokens(
    token_ids: object,
    winning_token_id: object,
) -> tuple[tuple[str, str], str]:
    if (
        not isinstance(token_ids, tuple)
        or len(token_ids) != 2
        or not all(
            isinstance(token_id, str) and token_id.strip()
            for token_id in token_ids
        )
    ):
        raise ValueError("market resolution requires two token IDs")
    normalized = (token_ids[0].strip(), token_ids[1].strip())
    if len(set(normalized)) != 2:
        raise ValueError("market resolution token IDs must be distinct")
    if not isinstance(winning_token_id, str):
        raise ValueError("winning token does not belong to the resolved market")
    winner = winning_token_id.strip()
    if winner not in normalized:
        raise ValueError("winning token does not belong to the resolved market")
    return normalized, winner
