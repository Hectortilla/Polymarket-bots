"""Failure details safe to expose through durable run state."""

from enum import StrEnum


class RunFailureReason(StrEnum):
    TRACKED_MARKET_ALLOWANCE = (
        "Tracked-market allowance reached. Reduce subscriptions or start a new run."
    )


NEW_RUN_GUIDANCE = "Start a new run to continue."
INTERRUPTION_DETAIL = (
    "Paper run interrupted because its worker stopped or lost its execution lease. "
    "Committed history is preserved. " + NEW_RUN_GUIDANCE
)


class RunSnapshotError(ValueError):
    """The persisted run cannot supply its required execution snapshot."""


class ExecutionOwnershipLost(RuntimeError):
    """The run no longer accepts progress from this executor."""


LAUNCH_ATTEMPT_UNAVAILABLE_DETAIL = (
    "The previous launch can no longer be recovered. Its history may have expired, "
    "or the request never reached the service. Review retained history before explicitly starting a new run."
)
LAUNCH_RECOVERY_KEY_REQUIRED_DETAIL = (
    "Launch recovery requires its original idempotency key."
)


class LaunchAttemptUnavailable(ValueError):
    """Recovery of a previous launch must never create a replacement run."""


def sanitized_failure_detail(error: Exception, reason: str) -> str:
    return f"{type(error).__name__}: {reason}"
