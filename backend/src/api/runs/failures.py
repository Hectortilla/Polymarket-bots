"""Failure details safe to expose through durable run state."""


def sanitized_failure_detail(error: Exception, reason: str) -> str:
    return f"{type(error).__name__}: {reason}"
