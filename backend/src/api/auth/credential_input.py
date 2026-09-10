"""Dependency-light credential input types shared by HTTP and mail configuration."""

from typing import Annotated

from email_validator import validate_email
from pydantic import AfterValidator, Field, SecretStr

from api.auth.policy import (
    EMAIL_MAX_LENGTH,
    EXISTING_PASSWORD_MIN_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
)


def normalize_email(value: str) -> str:
    normalized = validate_email(value.strip(), check_deliverability=False).normalized
    # Case folding can change Unicode length; validate the canonical result too.
    return validate_email(normalized.casefold(), check_deliverability=False).normalized


EmailAddress = Annotated[
    str,
    Field(min_length=1, max_length=EMAIL_MAX_LENGTH),
    AfterValidator(normalize_email),
]
Password = Annotated[
    SecretStr, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
]

# Existing secrets are checked against their hash; strength applies when choosing one.
ExistingPassword = Annotated[
    SecretStr,
    Field(min_length=EXISTING_PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
]
