"""Private data maintenance and explicit restoration reconciliation."""

import argparse
import asyncio
import os
import pwd
from uuid import UUID

from api.deployment.settings import StartupSettings
from api.lifecycle.commands import RESTORE_RECONCILIATION_FLAG, DataCommand
from api.lifecycle.runtime import execute


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(DataCommand.CLEAN)
    commands.add_parser(DataCommand.QUARANTINE_RESTORE)
    approve = commands.add_parser(DataCommand.APPROVE_RESTORED_ACCOUNT)
    approve.add_argument("user_id", type=UUID)
    approve.add_argument(
        RESTORE_RECONCILIATION_FLAG, action="store_true", required=True
    )
    args = parser.parse_args()
    try:
        settings = StartupSettings.from_env()
        actor = pwd.getpwuid(os.geteuid()).pw_name
        asyncio.run(
            execute(
                DataCommand(args.command),
                getattr(args, "user_id", None),
                settings,
                actor,
            )
        )
    except Exception:
        parser.exit(
            1,
            "Data maintenance failed; keep access closed and inspect private dependencies.\n",
        )
    print(
        "Data maintenance completed; restoration does not start application processes or reopen admissions."
    )


if __name__ == "__main__":
    main()
