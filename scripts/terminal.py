from __future__ import annotations

import os
import sys

NO_COLOR_ENV = "NO_COLOR"


def color_enabled() -> bool:
    return sys.stdout.isatty() and NO_COLOR_ENV not in os.environ
