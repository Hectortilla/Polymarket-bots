"""Controller-side proof of fresh deployment-key SSH and passwordless sudo access."""

import shlex
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress

from scripts.deployment.errors import DeploymentInputError
from scripts.deployment.paths import REPOSITORY

DEPLOYMENT_SSH_USER = "polybot"
SSH_CONNECTION_TIMEOUT_SECONDS = 10
SSH_PROBE_TIMEOUT_SECONDS = 30
SSHD_MAIN_PATH = "/etc/ssh/sshd_config"
SSHD_HARDENING_PATH = "/etc/ssh/sshd_config.d/00-polybot-hardening.conf"
SSH_HARDENING_POLICY = {
    "PasswordAuthentication": "no",
    "KbdInteractiveAuthentication": "no",
    "PermitRootLogin": "no",
    "PubkeyAuthentication": "yes",
}


class SSHConnectionContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    client_address: IPvAnyAddress
    client_port: int = Field(ge=1, le=65535)
    server_address: IPvAnyAddress
    server_port: int = Field(ge=1, le=65535)

    @classmethod
    def from_probe(cls, output: str) -> "SSHConnectionContext":
        fields = output.split()
        if len(fields) != 6 or fields[-2:] != [DEPLOYMENT_SSH_USER, "0"]:
            raise DeploymentInputError(
                "deployment SSH must prove passwordless root sudo"
            )
        return cls(
            client_address=fields[0],
            client_port=fields[1],
            server_address=fields[2],
            server_port=fields[3],
        )

    def sshd_selector(self) -> str:
        return (
            f"user={DEPLOYMENT_SSH_USER},host={self.client_address},"
            f"addr={self.client_address},laddr={self.server_address},lport={self.server_port}"
        )


class DeploymentSSHAccess(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)
    host: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9:][a-zA-Z0-9.:%_-]*$")
    port: int = Field(default=22, strict=True, ge=1, le=65535)
    private_key_file: Path | None = None
    common_args: str = ""
    extra_args: str = ""

    def verify(self) -> SSHConnectionContext:
        command = ["ssh"]
        # OpenSSH takes the first value of each -o setting. These must precede
        # inventory routing options, and no existing ControlMaster may satisfy proof.
        for setting in (
            "ControlMaster=no",
            "ControlPath=none",
            "BatchMode=yes",
            "PreferredAuthentications=publickey",
            "PasswordAuthentication=no",
            "KbdInteractiveAuthentication=no",
            "StrictHostKeyChecking=yes",
            "ForwardAgent=no",
            f"User={DEPLOYMENT_SSH_USER}",
            f"Port={self.port}",
            f"ConnectTimeout={SSH_CONNECTION_TIMEOUT_SECONDS}",
        ):
            command.extend(["-o", setting])
        command.extend(shlex.split(self.common_args))
        command.extend(shlex.split(self.extra_args))
        if self.private_key_file is not None:
            command.extend(
                [
                    "-i",
                    str(self.private_key_file.expanduser()),
                    "-o",
                    "IdentitiesOnly=yes",
                ]
            )
        command.extend(
            [
                "-p",
                str(self.port),
                "-S",
                "none",
                "-l",
                DEPLOYMENT_SSH_USER,
                "--",
                self.host,
                'printf "%s\\n" "$SSH_CONNECTION"; id -un; sudo -n id -u',
            ]
        )
        result = subprocess.run(
            command,
            # Ansible's delegated tasks start in the playbook directory, while
            # inventory key and known-hosts paths are relative to the repository.
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=SSH_PROBE_TIMEOUT_SECONDS,
        )
        return SSHConnectionContext.from_probe(result.stdout)


def require_hardened_ssh(effective: str) -> None:
    if not isinstance(effective, str):
        raise DeploymentInputError("expected textual effective SSH configuration")
    settings = dict(
        line.split(maxsplit=1) for line in effective.splitlines() if " " in line
    )
    if any(
        settings.get(key.lower()) != value
        for key, value in SSH_HARDENING_POLICY.items()
    ):
        raise DeploymentInputError(
            "effective SSH configuration conflicts with the key-only policy"
        )
