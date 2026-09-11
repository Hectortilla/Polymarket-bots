"""Validation for integral counts and identifiers at ingress boundaries."""


def validate_positive_int(value: int, name: str) -> None:
    if not is_positive_int(value):
        raise ValueError(f"{name} must be a positive integer")


def validate_nonnegative_int(value: int, name: str) -> None:
    if not is_nonnegative_int(value):
        raise ValueError(f"{name} must be a nonnegative integer")


def is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
