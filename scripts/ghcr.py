"""GHCR authentication without tokens in command arguments or build environments."""

import getpass
import os
import subprocess

REGISTRY = "ghcr.io"
TOKEN_ENV = "GITHUB_TOKEN"


def login(username: str) -> None:
    token = os.environ.pop(TOKEN_ENV, "") or getpass.getpass("GitHub token: ")
    if not username.strip() or not token.strip():
        raise ValueError("GHCR username and token are required")
    subprocess.run(
        ["docker", "login", REGISTRY, "-u", username, "--password-stdin"],
        input=token + "\n",
        text=True,
        check=True,
    )
