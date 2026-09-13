"""Activate an installed verified release bundle."""

import argparse
from pathlib import Path

from scripts.beta_release.activation import DeploymentActivator
from scripts.deployment.paths import DEFAULT_APP_DIRECTORY


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIRECTORY)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    DeploymentActivator(args.app_dir).activate(args.bundle, rollback=args.rollback)


if __name__ == "__main__":
    main()
