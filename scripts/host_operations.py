"""Host checks and mail transitions, independent of release activation."""

import argparse
import json
import socket
import ssl
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from api.lifecycle.policy import BACKUP_INTERVAL_HOURS

from scripts.beta_backup.archive_name import ArchiveName
from scripts.beta_backup.backup import BetaBackup
from scripts.beta_backup.database import ComposeDatabase
from scripts.beta_backup.remote import RemoteBackups
from scripts.beta_release import BetaRelease
from scripts.compose_project import DEFAULT_COMPOSE_PROJECT
from scripts.deployment.paths import BUNDLE_DIRECTORY_ENV
from scripts.deployment.state import DeploymentState
from scripts.private_files import read_regular, write_private

CERTIFICATE_WARNING_SECONDS = 7 * 24 * 3600
REQUIRED_ACTIVE_UNITS = (
    "docker",
    "tailscaled",
    "polybot-backup.timer",
    "polybot-backup-check.timer",
    "polybot-monitor.timer",
)


class HostOperations:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = json.loads(
            read_regular(root / "operations.json", required_mode=0o600)
        )
        self.state = DeploymentState(root)

    def remote(self) -> RemoteBackups:
        return RemoteBackups(
            self.root / "secrets/rclone.conf",
            self.config["remote"],
            self.root / "staging",
        )

    def release(self) -> BetaRelease:
        if self.state.pending():
            raise RuntimeError("deployment recovery is pending")
        return BetaRelease.from_manifest(
            self.state.manifest,
            DEFAULT_COMPOSE_PROJECT,
            compose_file=self.state.compose_file,
        )

    def backup(self) -> None:
        with self.state.locked():
            release = self.release()
            bundle = (
                Path(release.settings.extra_values[BUNDLE_DIRECTORY_ENV])
                / "release.tar.gz"
            )
            remote = self.remote()
            try:
                archive = BetaBackup(
                    ComposeDatabase(release.compose),
                    self.root / "staging",
                    self.root / "secrets/age-recipients.txt",
                ).create()
                remote.upload(archive, bundle)
            finally:
                self.bound_staging()

    def bound_staging(self) -> None:
        directory = self.root / "staging"
        cutoff = datetime.now(UTC).timestamp() - BACKUP_INTERVAL_HOURS * 3600
        archives = sorted(
            (
                p
                for p in directory.iterdir()
                if p.is_file() and not p.is_symlink() and ArchiveName.parse(p.name)
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in archives[2:]:
            path.unlink()
        for path in directory.glob(".incomplete-*"):
            if (
                path.is_file()
                and not path.is_symlink()
                and path.stat().st_mtime < cutoff
            ):
                path.unlink()

    def status(self) -> list[str]:
        failures = []
        checks = {
            "application": self.application,
            "host_services": self.services,
            "https_certificate": self.https,
            "backup_freshness": self.check_backup,
        }
        for code, check in checks.items():
            try:
                check()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                failures.append(code)
        return failures

    def check_backup(self) -> None:
        self.remote().require_recent()

    def application(self) -> None:
        release = self.release()
        release.compose.require_local_docker()
        release.require_healthy()
        release.compose.run(
            "exec", "-T", "recovery", "python", "-m", "api.operations", "status"
        )

    def services(self) -> None:
        # A multi-unit is-active succeeds when any unit is active.
        for unit in REQUIRED_ACTIVE_UNITS:
            subprocess.run(
                ["systemctl", "is-active", "--quiet", unit],
                check=True,
                timeout=30,
            )
        serve = json.loads(
            subprocess.check_output(
                ["tailscale", "serve", "status", "--json"], timeout=30
            )
        )
        if (
            not isinstance(serve, dict)
            or any(serve.get("AllowFunnel", {}).values())
            or not serve.get("Web")
        ):
            raise RuntimeError("private Serve configuration is not healthy")

        failed = subprocess.run(
            [
                "systemctl",
                "is-failed",
                "--quiet",
                "polybot-backup.service",
                "polybot-backup-check.service",
            ],
            check=False,
            timeout=30,
        )
        if failed.returncode != 1:
            raise RuntimeError("a required backup unit failed or is unavailable")

    def https(self) -> None:
        origin = self.config["origin"]
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("HTTPS origin required")
        context = ssl.create_default_context()
        with (
            socket.create_connection(
                (parsed.hostname, parsed.port or 443), timeout=15
            ) as connection,
            context.wrap_socket(connection, server_hostname=parsed.hostname) as tls,
        ):
            expiry = ssl.cert_time_to_seconds(tls.getpeercert()["notAfter"])
            if expiry - datetime.now(UTC).timestamp() < CERTIFICATE_WARNING_SECONDS:
                raise RuntimeError("HTTPS certificate renewal overdue")
        with urllib.request.urlopen(origin + "/api/v1/health", timeout=15) as response:
            if response.status != 200:
                raise RuntimeError("private HTTPS readiness failed")

    def notify(self, name: str, failures: list[str]) -> None:
        path = self.root / f".alert-{name}.json"
        previous = json.loads(read_regular(path)) if path.exists() else []
        failures = sorted(failures)
        print(json.dumps({"check": name, "failures": failures}), flush=True)
        if failures == previous:
            return
        status = "FAILURE" if failures else "RECOVERY"
        recipient = self.config["alert_to"]
        if "\n" in recipient or "\r" in recipient or recipient.startswith("-"):
            raise ValueError("invalid alert recipient")
        message = f"To: {recipient}\nSubject: Polybot {name} {status}\n\nChecks: {', '.join(failures) or 'healthy'}. Inspect private journald diagnostics.\n"
        subprocess.run(
            ["msmtp", "--file", str(self.root / "secrets/msmtprc"), "--", recipient],
            input=message,
            text=True,
            check=True,
            timeout=30,
        )
        # Only suppress an alert after SMTP accepted it; failures retry next tick.
        write_private(path, json.dumps(failures).encode())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "operation", choices=["backup", "backup-check", "monitor", "status"]
    )
    args = parser.parse_args()
    host = HostOperations(args.root)
    if args.operation in {"status", "monitor"}:
        failures = host.status()
    else:
        failures = []
        try:
            host.backup() if args.operation == "backup" else host.remote().require_recent()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            failures = [args.operation]
    host.notify(args.operation, failures)
    if failures:
        parser.exit(1, "Host checks failed; inspect the private journal.\n")


if __name__ == "__main__":
    main()
