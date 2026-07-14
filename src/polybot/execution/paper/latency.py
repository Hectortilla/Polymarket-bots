"""Paper-latency sampling kept separate from order and portfolio mutation."""

import random


def sample_latency_ms(
    base_latency_ms: int,
    jitter_ms: int,
    rng: random.Random,
) -> int:
    if jitter_ms <= 0:
        return base_latency_ms
    return base_latency_ms + rng.randrange(jitter_ms + 1)
