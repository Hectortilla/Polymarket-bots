"""Run host checks with sanitized failure output."""

import argparse
import subprocess
import tarfile
from pathlib import Path

from scripts.host_operations import HostOperations
from scripts.host_operations.contracts import HostOperation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("operation", type=HostOperation, choices=list(HostOperation))
    args = parser.parse_args()
    try:
        failures = HostOperations(args.root).execute(args.operation)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ):
        parser.exit(
            1, "Host operation failed; inspect private configuration and journal.\n"
        )
    if failures:
        parser.exit(1, "Host checks failed; inspect the private journal.\n")


if __name__ == "__main__":
    main()
