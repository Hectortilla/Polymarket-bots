"""Real encrypted backup and isolated restore acceptance, disposable projects only."""

import fcntl
import json
import shutil
import subprocess
import sys
import tarfile

from api.auth.recovery.schema import ACCOUNT_TOKENS_TABLE
from api.auth.schema import SESSIONS_TABLE, USERS_TABLE, UserColumn
from api.bots.schema import BOTS_TABLE_NAME
from api.deployment.release import RELEASE_ID_ENV
from api.deployment.services import POSTGRES_SERVICE, REDIS_SERVICE, DeploymentService
from api.events.schema import RUN_EVENTS_TABLE_NAME
from api.lifecycle.schema import RESTORE_QUARANTINED_AT_COLUMN
from api.operations.schema import CONTROL_TABLE, OperationControlColumn
from api.runs.schema import RUNS_TABLE_NAME, RunColumn
from api.runs.status import TERMINAL_RUN_STATUSES

from control_plane.deployment_smoke import DeploymentSmoke
from control_plane.release_bundle_fixture import worktree_bundle
from control_plane.sftp_fixture import sftp_server
from scripts.beta_backup.database import ComposeDatabase
from scripts.beta_backup.policy import AGE_BINARY
from scripts.beta_backup.restore import BetaRestore
from scripts.beta_release import BetaRelease
from scripts.deployment.attempt import LOCK_NAME
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.images import IMAGE_FIELDS
from scripts.deployment.paths import (
    CURRENT_RELEASE_NAME,
    HOST_COMPOSE_NAME,
    MANIFEST_NAME,
    OPERATIONS_CONFIGURATION_NAME,
    RELEASES_DIRECTORY_NAME,
    SECRETS_DIRECTORY_NAME,
    SOURCE_COMPOSE_PATH,
    STAGING_DIRECTORY_NAME,
)
from scripts.deployment.runtime_contracts import BUNDLE_DIRECTORY_ENV
from scripts.deployment.storage import POSTGRES_DATABASE, POSTGRES_USER
from scripts.deployment.transport_files import HostTransportFile
from scripts.private_files import write_private


class BackupRehearsal:
    def __init__(self) -> None:
        self.deployment = DeploymentSmoke()
        self.restored: BetaRelease | None = None

    def run(self) -> None:
        host = self.deployment
        try:
            host.prepare()
            release = BetaRelease.from_manifest(host.manifest, host.project)
            release.activate(rollback=False)
            host.install_runtime_fixture()
            host.exercise_runs()
            host.compose(
                "stop", DeploymentService.RECOVERY, DeploymentService.API, fixture=True
            )
            database = ComposeDatabase(release.compose)
            expected = self.inventory(database)
            assert all(item["count"] for item in expected.values())
            directory = host.directory / "backups"
            directory.mkdir(mode=0o700)
            identity = host.directory / "identity.age"
            subprocess.run(
                ["age-keygen", "-o", str(identity)],
                check=True,
                stderr=subprocess.DEVNULL,
            )
            identity.chmod(0o600)
            recipients = host.directory / "recipients.txt"
            recipients.write_bytes(
                subprocess.check_output(["age-keygen", "-y", str(identity)])
            )
            installed = host.directory / RELEASES_DIRECTORY_NAME / "v0.0.0"
            installed.mkdir(parents=True, mode=0o700)
            bundle = installed / RELEASE_BUNDLE_FILENAME
            bundle_images = {
                field: "rehearsal/image@" + host.values[field] for field in IMAGE_FIELDS
            }
            worktree_bundle(
                bundle,
                bundle_images | {RELEASE_ID_ENV: host.values[RELEASE_ID_ENV]},
                tag="v0.0.0",
            )
            with tarfile.open(bundle) as source:
                source.extractall(installed, filter="data")
            write_manifest(
                host.directory / MANIFEST_NAME,
                host.values | bundle_images | {BUNDLE_DIRECTORY_ENV: str(installed)},
            )
            shutil.copyfile(
                str(SOURCE_COMPOSE_PATH), host.directory / HOST_COMPOSE_NAME
            )
            (host.directory / CURRENT_RELEASE_NAME).symlink_to(
                installed, target_is_directory=True
            )
            staging = host.directory / STAGING_DIRECTORY_NAME
            staging.mkdir(mode=0o700)
            secrets_directory = host.directory / SECRETS_DIRECTORY_NAME
            shutil.copyfile(
                recipients, secrets_directory / HostTransportFile.AGE_RECIPIENTS
            )
            with sftp_server(host.directory / "sftp") as (remote, _storage, _process):
                write_private(
                    secrets_directory / HostTransportFile.RCLONE_CONFIG,
                    remote.transport.config.path.read_bytes(),
                )
                write_private(
                    host.directory / OPERATIONS_CONFIGURATION_NAME,
                    json.dumps(
                        {
                            "origin": "https://fixture.example.ts.net",
                            "alert_to": "operator@example.com",
                            "remote": remote.transport.config.directory.remote,
                        }
                    ).encode(),
                )
                # The host entrypoint is exercised in its own subprocess. Its
                # Compose project is scoped to this rehearsal's disposable stack.
                command = [
                    sys.executable,
                    "-c",
                    "import sys; import scripts.host_operations as host; from scripts.host_operations.__main__ import main; host.DEFAULT_COMPOSE_PROJECT = sys.argv.pop(1); main()",
                    host.project,
                    "--root",
                    str(host.directory),
                    "backup",
                ]
                subprocess.run(command, check=True)
                remote.require_recent()
                pairs = remote.inventory.completed_pairs()
                assert len(pairs) == 1
                with (host.directory / LOCK_NAME).open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    assert (
                        subprocess.run(
                            command, capture_output=True, check=False
                        ).returncode
                        == 1
                    )
                assert len(remote.inventory.completed_pairs()) == 1
                assert not list(staging.iterdir())
                downloaded = host.directory / "downloaded"
                downloaded.mkdir(mode=0o700)
                downloaded_archive, _ = remote.download(
                    pairs[0].archive_filename, downloaded
                )
            self.reject_invalid_database_dump(recipients, identity)
            restore = BetaRestore(
                host.manifest, downloaded_archive, identity, host.directory
            )
            self.restored = BetaRelease.from_manifest(host.manifest, restore.project)
            project, seconds = restore.restore()
            restored_database = ComposeDatabase(self.restored.compose)
            assert self.inventory(restored_database) == expected
            assert (
                self.sql(
                    restored_database,
                    f"SELECT {OperationControlColumn.ADMISSIONS_PAUSED} FROM {CONTROL_TABLE}",
                )
                == "t"
            )
            count = int(
                self.sql(
                    restored_database,
                    f"SELECT count(*) FROM {USERS_TABLE} WHERE {RESTORE_QUARANTINED_AT_COLUMN} IS NULL",
                )
            )
            assert count == 0
            for table in (SESSIONS_TABLE, ACCOUNT_TOKENS_TABLE):
                assert (
                    int(self.sql(restored_database, f"SELECT count(*) FROM {table}"))
                    == 0
                )
            terminal = ",".join(f"'{state.value}'" for state in TERMINAL_RUN_STATUSES)
            assert (
                int(
                    self.sql(
                        restored_database,
                        f"SELECT count(*) FROM {RUNS_TABLE_NAME} WHERE {RunColumn.STATUS} NOT IN ({terminal})",
                    )
                )
                == 0
            )
            running = subprocess.check_output(
                restored_database.project.command(
                    "ps", "--status", "running", "--services"
                ),
                env=restored_database.project.environment,
                text=True,
            ).splitlines()
            assert set(running) == {POSTGRES_SERVICE, REDIS_SERVICE}
            (host.directory / "restore-result.json").write_text(
                json.dumps(
                    {
                        "isolated_project": project,
                        "seconds": seconds,
                        "verified": list(expected),
                        "quarantined": True,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(
                f"Encrypted backup/restore passed in {seconds:.1f}s; accounts, ownership, bots/revisions and history preserved; no jobs launched.",
                flush=True,
            )
        finally:
            host.stop_tls()
            if self.restored is not None:
                self.restored.compose.run("down", "--volumes", "--remove-orphans")
            if host.manifest.exists():
                host.compose("down", "--volumes", "--remove-orphans")

    def reject_invalid_database_dump(self, recipients, identity) -> None:
        invalid_archive = self.deployment.directory / "invalid-database.dump.age"
        with invalid_archive.open("wb") as encrypted:
            subprocess.run(
                [AGE_BINARY, "--encrypt", "--recipients-file", str(recipients)],
                input=b"not a PostgreSQL custom archive",
                stdout=encrypted,
                check=True,
            )
        restore = BetaRestore(
            self.deployment.manifest,
            invalid_archive,
            identity,
            self.deployment.directory,
        )
        failed_release = BetaRelease.from_manifest(
            self.deployment.manifest, restore.project
        )
        try:
            try:
                restore.restore()
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("invalid database dump reported restore success")
            database = ComposeDatabase(failed_release.compose)
            running = subprocess.check_output(
                failed_release.compose.command(
                    "ps", "--status", "running", "--services"
                ),
                env=failed_release.compose.environment,
                text=True,
            ).splitlines()
            assert set(running) == {POSTGRES_SERVICE, REDIS_SERVICE}
            assert self.sql(database, f"SELECT to_regclass('{USERS_TABLE}')") == ""
        finally:
            failed_release.compose.run("down", "--volumes", "--remove-orphans")
            invalid_archive.unlink(missing_ok=True)

    def inventory(self, database: ComposeDatabase) -> dict:
        inventory = {}
        for table in (
            USERS_TABLE,
            BOTS_TABLE_NAME,
            RUNS_TABLE_NAME,
            RUN_EVENTS_TABLE_NAME,
        ):
            projection = (
                f"{UserColumn.ID}, {UserColumn.EMAIL}, {UserColumn.PASSWORD_HASH}, {UserColumn.CREATED_AT}"
                if table == USERS_TABLE
                else "*"
            )
            result = self.sql(
                database,
                f"SELECT json_build_object('count', count(*), 'digest', md5(string_agg(row_to_json(t)::text, '' ORDER BY id))) FROM (SELECT {projection} FROM {table}) t",
            )
            inventory[table] = json.loads(result)
        return inventory

    def sql(self, database: ComposeDatabase, statement: str) -> str:
        return self.deployment.command(
            *database.project.command(
                "exec",
                "-T",
                POSTGRES_SERVICE,
                "psql",
                "--username",
                POSTGRES_USER,
                "--dbname",
                POSTGRES_DATABASE,
                "-At",
                "-c",
                statement,
            )
        ).strip()


if __name__ == "__main__":
    BackupRehearsal().run()
