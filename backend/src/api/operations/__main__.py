"""OS-authorized maintenance CLI; browser credentials grant no capability."""

import argparse
import asyncio
import os
import pwd
from uuid import UUID

from api.deployment.settings import StartupSettings
from api.operations.commands import (
    ALL_OPERATION_COMMANDS,
    CommandRequest,
    OperationCommand,
    ReadCommand,
)
from api.operations.contracts import OperationStatus
from api.operations.runtime import execute
from api.operations.schema import OperatorAction

OPERATION_FAILED_DETAIL = "Operation failed; verify private dependencies and matching schema. No successful mutation is claimed."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", type=parse_command, choices=ALL_OPERATION_COMMANDS)
    parser.add_argument("target", type=UUID, nargs="?")
    args = parser.parse_args()
    try:
        request = CommandRequest(args.command, args.target)
    except ValueError as error:
        parser.error(str(error))
    try:
        actor = pwd.getpwuid(os.geteuid()).pw_name
        result = asyncio.run(execute(request, StartupSettings.from_env(), actor))
    except Exception:
        parser.exit(1, OPERATION_FAILED_DETAIL + "\n")
    print(result.model_dump_json())
    if isinstance(result, OperationStatus) and not result.healthy:
        parser.exit(1)


def parse_command(value: str) -> OperationCommand:
    try:
        return ReadCommand(value)
    except ValueError:
        try:
            return OperatorAction(value)
        except ValueError:
            raise argparse.ArgumentTypeError("unknown operation command") from None


if __name__ == "__main__":
    main()
