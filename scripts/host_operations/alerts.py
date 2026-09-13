"""Durable alert transitions after SMTP acceptance."""

import fcntl
import json
import subprocess
from pathlib import Path

from scripts.deployment.errors import DeploymentInputError
from scripts.deployment.paths import SECRETS_DIRECTORY_NAME
from scripts.deployment.transport_files import HostTransportFile
from scripts.host_operations.contracts import HostCheckCode, HostOperation
from scripts.host_operations.policy import (
    HOST_COMMAND_TIMEOUT_SECONDS,
)
from scripts.private_files import (
    PRIVATE_FILE_MODE,
    read_regular,
    regular_file,
    write_private,
)


class HostAlerts:
    def __init__(self, root: Path, recipient: str) -> None:
        self.root = root
        self.recipient = recipient

    def notify(self, operation: HostOperation, failures: list[HostCheckCode]) -> None:
        path = self.root / f".alert-{operation}.json"
        # Serialize the read/send/write transition across manual and timer runs.
        with regular_file(path.with_suffix(".lock"), create=True) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = self.read_state(path)
            failures = sorted(failures)
            print(json.dumps({"check": operation, "failures": failures}), flush=True)
            if failures == previous:
                return
            status = "FAILURE" if failures else "RECOVERY"
            message = f"To: {self.recipient}\nSubject: Polybot {operation} {status}\n\nChecks: {', '.join(failures) or 'healthy'}. Inspect private journald diagnostics.\n"
            subprocess.run(
                [
                    "msmtp",
                    "--file",
                    str(
                        self.root
                        / SECRETS_DIRECTORY_NAME
                        / HostTransportFile.SMTP_CONFIG
                    ),
                    "--",
                    self.recipient,
                ],
                input=message,
                text=True,
                check=True,
                timeout=HOST_COMMAND_TIMEOUT_SECONDS,
            )
            # Failed or uncertain delivery retries next tick. Standard SMTP can
            # duplicate an accepted message if the process dies before this write.
            write_private(path, json.dumps(failures).encode())

    @staticmethod
    def read_state(path: Path) -> list[HostCheckCode]:
        if not path.exists() and not path.is_symlink():
            return []
        record = json.loads(read_regular(path, required_mode=PRIVATE_FILE_MODE))
        if not isinstance(record, list):
            raise DeploymentInputError("invalid persisted host alert state")
        return sorted(HostCheckCode(value) for value in record)
