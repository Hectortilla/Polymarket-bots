"""Host operational commands and stable aggregate health results."""

import subprocess
from pathlib import Path

from api.deployment.services import DeploymentService
from api.operations.commands import ReadCommand

from scripts.beta_backup.remote import RemoteBackups
from scripts.beta_backup.workflow import BackupWorkflow
from scripts.beta_release import BetaRelease
from scripts.compose_project import DEFAULT_COMPOSE_PROJECT
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.deployment.bundle.installation import InstalledBundle
from scripts.deployment.paths import SECRETS_DIRECTORY_NAME, STAGING_DIRECTORY_NAME
from scripts.deployment.state import DeploymentState
from scripts.deployment.transport_files import HostTransportFile
from scripts.host_operations.alerts import HostAlerts
from scripts.host_operations.config import HostOperationsConfig
from scripts.host_operations.contracts import HostCheckCode, HostOperation
from scripts.host_operations.probes import HostProbes


class HostOperations:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = HostOperationsConfig.read(root)
        self.state = DeploymentState(root)
        self.alerts = HostAlerts(root, str(self.config.alert_to))
        self.probes = HostProbes(self.config)

    def execute(self, operation: HostOperation) -> list[HostCheckCode]:
        if operation in {HostOperation.STATUS, HostOperation.MONITOR}:
            failures = self.status()
        else:
            failures = []
            try:
                if operation is HostOperation.BACKUP:
                    self.backup()
                else:
                    self.remote().require_recent()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                failures = [HostCheckCode(operation.value)]
        self.alerts.notify(operation, failures)
        return failures

    def status(self) -> list[HostCheckCode]:
        failures = []
        checks = {
            HostCheckCode.APPLICATION: self.application,
            HostCheckCode.HOST_SERVICES: self.probes.services,
            HostCheckCode.HTTPS_CERTIFICATE: self.probes.https,
            HostCheckCode.BACKUP_FRESHNESS: self.check_backup,
        }
        for code, check in checks.items():
            try:
                check()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                failures.append(code)
        return failures

    def backup(self) -> None:
        # Deployment and backup share this lock so bundle identity, Compose and
        # database schema cannot change between snapshot selection and upload.
        with self.state.locked():
            release = self.release()
            installed = InstalledBundle.read(
                release.settings.require_bundle_directory(), self.root
            )
            release_bundle_archive_path = installed.directory / RELEASE_BUNDLE_FILENAME
            BackupWorkflow(
                release,
                self.remote(),
                self.root / SECRETS_DIRECTORY_NAME / HostTransportFile.AGE_RECIPIENTS,
                self.root / STAGING_DIRECTORY_NAME,
            ).create(release_bundle_archive_path)

    def application(self) -> None:
        release = self.release()
        release.compose.require_local_docker()
        release.require_healthy()
        release.compose.run(
            "exec",
            "-T",
            DeploymentService.RECOVERY,
            "python",
            "-m",
            "api.operations",
            ReadCommand.STATUS,
        )

    def check_backup(self) -> None:
        self.remote().require_recent()

    def remote(self) -> RemoteBackups:
        return RemoteBackups(
            self.root / SECRETS_DIRECTORY_NAME / HostTransportFile.RCLONE_CONFIG,
            self.config.remote,
            self.root / STAGING_DIRECTORY_NAME,
        )

    def release(self) -> BetaRelease:
        if self.state.pending():
            raise RuntimeError("deployment recovery is pending")
        release = BetaRelease.from_manifest(
            self.state.manifest,
            DEFAULT_COMPOSE_PROJECT,
            compose_file=self.state.compose_file,
        )
        installed = InstalledBundle.read(
            release.settings.require_bundle_directory(), self.root
        )
        installed.require_images(release.settings.images)
        installed.require_current(self.root)
        return release
