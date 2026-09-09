"""Account-link and reauthentication failures, independent of persistence."""


class InvalidAccountToken(Exception):
    """No currently redeemable link exists for this purpose."""


class ReauthenticationFailed(Exception):
    """The current session and password did not authorize this operation."""
