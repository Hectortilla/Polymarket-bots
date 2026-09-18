"""Typed Ansible controller commands; failures never echo secret inputs."""

import argparse
import json
import os
import subprocess
import sys
from enum import StrEnum
from pathlib import Path

from api.auth.config import AUTH_ORIGIN_ENV

from scripts.deployment.ansible_contract import deployment_contract
from scripts.deployment.bootstrap_inputs import BootstrapInputError, BootstrapInputs
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.deployment.dotenv import parse_values
from scripts.deployment.ingress import IngressSettings
from scripts.deployment.inventory import DeploymentInventory
from scripts.deployment.paths import CI_INPUTS_FILENAME
from scripts.deployment.provisioning import ContainerSecretInputs
from scripts.deployment.release_inputs import ReleaseIdentity, ReleaseInputs
from scripts.deployment.runtime_contracts import DEFAULT_HTTP_PORT, HTTP_PORT_ENV
from scripts.deployment.ssh_access import DeploymentSSHAccess, require_hardened_ssh
from scripts.deployment.tailscale import (
    EnrollmentStatus,
    PrivateServe,
    ServeStatus,
    TailnetStatus,
)


class ControllerOperation(StrEnum):
    BOOTSTRAP = "bootstrap"
    SECRETS = "secrets"
    INVENTORY = "inventory"
    PLATFORM = "platform"
    RELEASE = "release"
    INPUTS = "inputs"
    TAILNET = "tailnet"
    ENROLLMENT = "enrollment"
    SERVE = "serve"
    SSH_ACCESS = "ssh-access"
    SSH_POLICY = "ssh-policy"
    INGRESS = "ingress"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", type=ControllerOperation, choices=list(ControllerOperation)
    )
    args = parser.parse_args()
    try:
        if args.operation is ControllerOperation.INPUTS:
            ReleaseInputs.from_environment(
                os.environ, Path("bundle") / RELEASE_BUNDLE_FILENAME
            ).write(Path(CI_INPUTS_FILENAME))
            return
        record = json.load(sys.stdin)
        match args.operation:
            case ControllerOperation.INGRESS:
                runtime = parse_values(record["runtime"])
                DeploymentInventory.model_validate(
                    record["variables"]
                ).require_bootstrapped(
                    IngressSettings.model_validate(record["operations"]),
                    runtime.get(AUTH_ORIGIN_ENV),
                    int(runtime.get(HTTP_PORT_ENV) or DEFAULT_HTTP_PORT),
                )
            case ControllerOperation.SSH_ACCESS:
                connection = DeploymentSSHAccess.model_validate(record).verify()
                print(json.dumps({"sshd_selector": connection.sshd_selector()}))
            case ControllerOperation.SSH_POLICY:
                require_hardened_ssh(record["effective"])
            case ControllerOperation.BOOTSTRAP:
                BootstrapInputs.from_record(record["secrets"]).require_valid(
                    DeploymentInventory.model_validate(record["variables"])
                )
            case ControllerOperation.SECRETS:
                print(
                    json.dumps(
                        [
                            secret.model_dump(mode="json")
                            for secret in ContainerSecretInputs.model_validate(
                                record
                            ).render()
                        ]
                    )
                )
            case ControllerOperation.INVENTORY:
                inventory = DeploymentInventory.model_validate(record["variables"])
                inventory.require_host(
                    record["host_count"],
                    record["host_distribution"],
                    record["host_architecture"],
                )
                print(
                    json.dumps(
                        {
                            "contract": deployment_contract(),
                            "variables": inventory.model_dump(
                                mode="json", by_alias=True
                            ),
                        }
                    )
                )
            case ControllerOperation.PLATFORM:
                inventory = DeploymentInventory.from_ansible_inventory(record)
                print("platform=linux/" + inventory.arch)
            case ControllerOperation.RELEASE:
                ReleaseIdentity.model_validate(record)
            case ControllerOperation.ENROLLMENT:
                print(
                    json.dumps(
                        EnrollmentStatus(
                            running=TailnetStatus.from_record(record).running
                        )
                    )
                )
            case ControllerOperation.TAILNET:
                TailnetStatus.from_record(record["status"]).require_origin(
                    record["origin"]
                )
            case ControllerOperation.SERVE:
                serve = PrivateServe.from_record(record["status"])
                print(
                    json.dumps(
                        ServeStatus(
                            configured=serve.matches(
                                record["origin"], record["http_port"]
                            )
                        )
                    )
                )
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        if args.operation is ControllerOperation.BOOTSTRAP:
            diagnostic = (
                str(error)
                if isinstance(error, BootstrapInputError)
                else "Bootstrap preflight could not validate the private configuration; "
                "check inventory, Vault and controller prerequisites."
            )
            print(json.dumps({"error": diagnostic}))
            parser.exit(1)
        if args.operation is ControllerOperation.SSH_ACCESS:
            parser.exit(
                1,
                "Fresh deployment-key SSH/sudo verification failed; check the "
                "deployment key, known_hosts, routing and passwordless sudo. "
                "Relative paths resolve from the repository root.\n",
            )
        parser.exit(
            1,
            "Invalid deployment controller input; inspect the private configuration.\n",
        )


if __name__ == "__main__":
    main()
