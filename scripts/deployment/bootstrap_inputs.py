"""Validate private bootstrap inputs locally before changing the target host."""

import subprocess
import tempfile
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scripts.deployment.errors import DeploymentInputError
from scripts.deployment.ingress import IngressMode
from scripts.deployment.inventory import DeploymentInventory
from scripts.private_files import write_private

BOOTSTRAP_INPUT_TIMEOUT_SECONDS = 30


class BootstrapInputError(DeploymentInputError):
    """Operator-safe bootstrap diagnostic containing no supplied values."""


class BootstrapInputs(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)
    ssh_public_key: str = Field(min_length=1, repr=False)
    sftp_private_key: str = Field(default="", repr=False)
    sftp_known_hosts: str = Field(default="", repr=False)
    age_recipients: str = Field(default="", repr=False)
    smtp_username: str = Field(min_length=1, repr=False)
    smtp_password: str = Field(min_length=1, repr=False)
    tailscale_authkey: str = Field(default="", repr=False)
    cloudflare_tunnel_token: str = Field(default="", repr=False)
    enroll_tailnet: bool = True

    @classmethod
    def from_record(cls, record: object) -> Self:
        try:
            return cls.model_validate(record)
        except ValidationError as error:
            fields = sorted(
                {
                    item["loc"][0]
                    for item in error.errors(include_input=False, include_context=False)
                    if item["loc"] and item["loc"][0] in cls.model_fields
                }
            )
            names = ", ".join("polybot_" + field for field in fields)
            raise BootstrapInputError(
                "Missing or invalid bootstrap fields: " + (names or "secrets object")
            ) from None

    def require_valid(self, inventory: DeploymentInventory) -> None:
        if inventory.ingress is IngressMode.CLOUDFLARE and (
            not self.cloudflare_tunnel_token
            or any(character.isspace() for character in self.cloudflare_tunnel_token)
            or self.cloudflare_tunnel_token.startswith("REPLACE")
        ):
            raise BootstrapInputError(
                "polybot_cloudflare_tunnel_token: a Cloudflare tunnel token is required "
                "without whitespace or a REPLACE placeholder"
            )
        if self.enroll_tailnet and not self.tailscale_authkey.startswith("tskey-auth-"):
            raise BootstrapInputError(
                "polybot_tailscale_authkey: a tagged Tailscale enrollment key is required "
                "with the tskey-auth- prefix"
            )
        public_records = self.ssh_public_key.strip().splitlines()
        if len(public_records) != 1 or not public_records[0].startswith(
            ("ssh-", "ecdsa-", "sk-")
        ):
            raise BootstrapInputError(
                "polybot_ssh_public_key: an OpenSSH public-key record is required"
            )
        if not self.smtp_username.strip() or not self.smtp_password.strip():
            raise BootstrapInputError(
                "polybot_smtp_username / polybot_smtp_password: SMTP credentials are required"
            )
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
            commands = [
                (
                    ["ssh-keygen", "-l", "-f", str(public_key)],
                    "polybot_ssh_public_key must contain a parseable OpenSSH public key",
                )
            ]
            if inventory.backups_enabled:
                if not all(
                    value.strip()
                    for value in (
                        self.sftp_private_key,
                        self.sftp_known_hosts,
                        self.age_recipients,
                    )
                ):
                    raise BootstrapInputError(
                        "SFTP credentials and age recipients are required when backups are enabled"
                    )
                host = inventory.sftp_host
                if inventory.sftp_port != 22:
                    host = f"[{host}]:{inventory.sftp_port}"
                commands.extend(
                    [
                        (
                            ["ssh-keygen", "-y", "-P", "", "-f", str(private_key)],
                            "polybot_sftp_private_key must be a parseable private key without a passphrase",
                        ),
                        (
                            ["ssh-keygen", "-l", "-f", str(known_hosts)],
                            "polybot_sftp_known_hosts must contain parseable OpenSSH host records",
                        ),
                        (
                            ["ssh-keygen", "-F", host, "-f", str(known_hosts)],
                            "polybot_sftp_known_hosts must match the configured SFTP host and port",
                        ),
                        (
                            ["age", "--encrypt", "--recipients-file", str(recipients)],
                            "polybot_age_recipients must contain valid age encryption recipients",
                        ),
                    ]
                )
            for command, diagnostic in commands:
                try:
                    subprocess.run(
                        command,
                        input=b"",
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=BOOTSTRAP_INPUT_TIMEOUT_SECONDS,
                    )
                except FileNotFoundError:
                    raise BootstrapInputError(
                        f"Install {command[0]} on the controller before bootstrap"
                    ) from None
                except subprocess.TimeoutExpired:
                    raise BootstrapInputError(
                        f"Controller validation timed out: {diagnostic}"
                    ) from None
                except subprocess.CalledProcessError:
                    raise BootstrapInputError(diagnostic) from None
