from __future__ import annotations

import os
import sys

NO_COLOR_ENV = "NO_COLOR"


def color_enabled() -> bool:
    return sys.stdout.isatty() and NO_COLOR_ENV not in os.environ


def color(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if color_enabled() else text


def good(text: str) -> str:
    return color("32", text)


def bad(text: str) -> str:
    return color("31", text)


def warn(text: str) -> str:
    return color("33", text)


def dim(text: str) -> str:
    return color("90", text)


def heading(text: str) -> str:
    return color("1;36", text)
