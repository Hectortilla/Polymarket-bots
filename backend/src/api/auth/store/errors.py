"""Database conflict classification for account registration."""

from sqlalchemy.exc import IntegrityError

from api.auth.schema import USERS_EMAIL_CONSTRAINT_NAME


class RegistrationConflictError(Exception):
    """The normalized email already belongs to an account."""

    @staticmethod
    def matches(error: IntegrityError) -> bool:
        cause = error.orig.__cause__
        return getattr(cause, "constraint_name", None) == USERS_EMAIL_CONSTRAINT_NAME
