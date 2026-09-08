"""Deterministic paper-latency arithmetic."""


def latency_ms(
    base_latency_ms: int,
    jitter_ms: int,
    jitter_offset_ms: int,
) -> int:
    if jitter_offset_ms < 0 or jitter_offset_ms > jitter_ms:
        raise ValueError("paper latency jitter offset is outside the configured range")
    return _latency_ms(base_latency_ms, jitter_offset_ms)


def _latency_ms(base_latency_ms: int, jitter_offset_ms: int) -> int:
    return base_latency_ms + jitter_offset_ms
