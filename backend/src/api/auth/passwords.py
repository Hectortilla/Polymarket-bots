"""Argon2id work isolated from the async event loop."""

from functools import partial

import anyio
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from api.auth.policy import ARGON_ITERATIONS, ARGON_MEMORY_KIB, ARGON_PARALLELISM


class PasswordVerificationError(Exception):
    """Persisted password state could not be verified safely."""


HASHER = PasswordHasher(
    time_cost=ARGON_ITERATIONS,
    memory_cost=ARGON_MEMORY_KIB,
    parallelism=ARGON_PARALLELISM,
    type=Type.ID,
)
# A valid hash with the identical work factor avoids a fast unknown-user path.
DUMMY_HASH = "$argon2id$v=19$m=19456,t=2,p=1$MTIzNDU2Nzg5MGFiY2RlZg$zdGPGhpJzWPZFQJi+pueAi/hPgXVmpIUqEmkWo9PQWw"


async def hash_password(password: str) -> str:
    return await anyio.to_thread.run_sync(HASHER.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    return await anyio.to_thread.run_sync(partial(_verify, password_hash, password))


def _verify(password_hash: str, password: str) -> bool:
    try:
        return HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError):
        raise PasswordVerificationError("password verification unavailable") from None
