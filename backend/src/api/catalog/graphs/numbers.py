"""Exact graph Number ingress and arithmetic policy."""

import re
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, InvalidOperation

INVALID_NUMBER_MESSAGE = "Enter a valid number"


GRAPH_NUMBER_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
MAX_NUMBER_TEXT_LENGTH = 256
MAX_NUMBER_EXPONENT = 1000
MAX_ROUND_DECIMAL_PLACES = 1000
GRAPH_ROUND_MODE = ROUND_HALF_UP
GRAPH_NUMBER_PATTERN = r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"


def number_from_text(value: str) -> Decimal:
    if len(value) > MAX_NUMBER_TEXT_LENGTH:
        raise ValueError("Number is too long")
    if re.fullmatch(GRAPH_NUMBER_PATTERN, value) is None:
        raise ValueError(INVALID_NUMBER_MESSAGE)
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(INVALID_NUMBER_MESSAGE) from error
    if not number.is_finite() or (
        not number.is_zero() and abs(number.adjusted()) > MAX_NUMBER_EXPONENT
    ):
        raise ValueError("Number must be finite and within the supported range")
    return number


def whole_number(value: Decimal, name: str) -> int:
    if value < 0 or value != value.to_integral_value():
        raise ValueError(f"{name} requires a nonnegative whole number")
    return int(value)
