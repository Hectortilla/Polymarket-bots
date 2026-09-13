"""Typed Ansible controller commands; failures never echo secret inputs."""

import argparse
import json
import os
import subprocess
import sys
from enum import StrEnum
from pathlib import Path

from scripts.deployment.ansible_contract import deployment_contract
from scripts.deployment.bootstrap_inputs import BootstrapInputs
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.deployment.inventory import DeploymentInventory
from scripts.deployment.paths import CI_INPUTS_FILENAME
from scripts.deployment.provisioning import ContainerSecretInputs
from scripts.deployment.release_inputs import ReleaseIdentity, ReleaseInputs
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
            case ControllerOperation.BOOTSTRAP:
                BootstrapInputs.model_validate(record["secrets"]).require_valid(
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
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        parser.exit(
            1,
            "Invalid deployment controller input; inspect the private configuration.\n",
        )


if __name__ == "__main__":
    main()
