"""Optional host-owned scope around the final synchronous paper portfolio mutation."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

type ExecutionScope = Callable[[], AbstractAsyncContextManager[None]]
