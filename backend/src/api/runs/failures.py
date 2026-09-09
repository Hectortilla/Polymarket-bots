"""Failure details safe to expose through durable run state."""


from enum import StrEnum


class RunFailureReason(StrEnum):
    TRACKED_MARKET_ALLOWANCE = "Tracked-market allowance reached. Reduce subscriptions or start a new run."


def sanitized_failure_detail(error: Exception, reason: str) -> str:
    return f"{type(error).__name__}: {reason}"
