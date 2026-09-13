"""Validate private bootstrap inputs locally before changing the target host."""

import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from scripts.deployment.errors import DeploymentInputError
from scripts.deployment.inventory import DeploymentInventory
from scripts.private_files import write_private

BOOTSTRAP_INPUT_TIMEOUT_SECONDS = 30


class BootstrapInputs(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)
    ssh_public_key: str = Field(min_length=1, repr=False)
    sftp_private_key: str = Field(min_length=1, repr=False)
    sftp_known_hosts: str = Field(min_length=1, repr=False)
    age_recipients: str = Field(min_length=1, repr=False)
    smtp_username: str = Field(min_length=1, repr=False)
    smtp_password: str = Field(min_length=1, repr=False)
    tailscale_authkey: str = Field(default="", repr=False)
    enroll_tailnet: bool = True

    def require_valid(self, inventory: DeploymentInventory) -> None:
        if self.enroll_tailnet and not self.tailscale_authkey.startswith("tskey-auth-"):
            raise DeploymentInputError("a tagged Tailscale enrollment key is required")
        public_records = self.ssh_public_key.strip().splitlines()
        if len(public_records) != 1 or not public_records[0].startswith(
            ("ssh-", "ecdsa-", "sk-")
        ):
            raise DeploymentInputError("an OpenSSH public-key record is required")
        if not self.smtp_username.strip() or not self.smtp_password.strip():
            raise DeploymentInputError("SMTP credentials are required")
        with tempfile.TemporaryDirectory(
            prefix="polybot-bootstrap-inputs-"
        ) as temporary:
            directory = Path(temporary)
            public_key = directory / "public_key"
            private_key = directory / "private_key"
            known_hosts = directory / "known_hosts"
            recipients = directory / "recipients"
            for path, content in (
                (public_key, self.ssh_public_key),
                (private_key, self.sftp_private_key),
                (known_hosts, self.sftp_known_hosts),
                (recipients, self.age_recipients),
            ):
                write_private(path, (content.strip() + "\n").encode())
            host = inventory.sftp_host
            if inventory.sftp_port != 22:
                host = f"[{host}]:{inventory.sftp_port}"
            commands = [
                ["ssh-keygen", "-l", "-f", str(public_key)],
                ["ssh-keygen", "-y", "-P", "", "-f", str(private_key)],
                ["ssh-keygen", "-l", "-f", str(known_hosts)],
                ["ssh-keygen", "-F", host, "-f", str(known_hosts)],
                ["age", "--encrypt", "--recipients-file", str(recipients)],
            ]
            for command in commands:
                subprocess.run(
                    command,
                    input=b"",
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=BOOTSTRAP_INPUT_TIMEOUT_SECONDS,
                )
