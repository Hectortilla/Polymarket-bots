"""Independent deterministic random streams for archive replay."""

import hashlib

BROKER_SEED_PURPOSE = "broker"
STRATEGY_SEED_PURPOSE = "strategy"


def derived_seed(seed: int, purpose: str) -> int:
    """Derive an independent deterministic random stream from one run seed."""
    digest = hashlib.sha256(f"{seed}:{purpose}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")
