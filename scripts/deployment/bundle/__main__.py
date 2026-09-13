"""Build or verify a committed release bundle."""

import argparse
import json
from pathlib import Path
from typing import assert_never

from scripts.deployment.bundle import ReleaseBundle
from scripts.deployment.bundle.contracts import BundleOperation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser(BundleOperation.CREATE)
    build.add_argument("--source", type=Path, default=Path.cwd())
    build.add_argument("--images", type=Path, required=True)
    build.add_argument("--tag", required=True)
    build.add_argument("--output", type=Path, required=True)
    check = commands.add_parser(BundleOperation.VERIFY)
    check.add_argument("bundle", type=Path)
    check.add_argument("--commit")
    check.add_argument("--tag")
    args = parser.parse_args()
    operation = BundleOperation(args.operation)
    match operation:
        case BundleOperation.CREATE:
            ReleaseBundle.create(args.source, args.images, args.tag, args.output)
        case BundleOperation.VERIFY:
            bundle = ReleaseBundle.from_archive(
                args.bundle, commit=args.commit, tag=args.tag
            )
            print(json.dumps(bundle.metadata.to_record(), sort_keys=True))
        case _:
            assert_never(operation)


if __name__ == "__main__":
    main()
