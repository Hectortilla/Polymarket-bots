"""Real encrypted backup and isolated restore acceptance, disposable projects only."""

import json
import subprocess

from api.auth.recovery.schema import ACCOUNT_TOKENS_TABLE
from api.auth.schema import SESSIONS_TABLE, USERS_TABLE, UserColumn
from api.bots.schema import BOTS_TABLE_NAME
from api.deployment.services import POSTGRES_SERVICE, REDIS_SERVICE, DeploymentService
from api.events.schema import RUN_EVENTS_TABLE_NAME
from api.lifecycle.schema import RESTORE_QUARANTINED_AT_COLUMN
from api.operations.schema import CONTROL_TABLE, OperationControlColumn
from api.runs.schema import RUNS_TABLE_NAME, RunColumn
from api.runs.status import TERMINAL_RUN_STATUSES

from control_plane.deployment_smoke import DeploymentSmoke
from scripts.beta_backup.archives import BackupArchives
from scripts.beta_backup.backup import BetaBackup
from scripts.beta_backup.database import (
    POSTGRES_DATABASE,
    POSTGRES_USER,
    ComposeDatabase,
)
from scripts.beta_backup.policy import AGE_BINARY
from scripts.beta_backup.restore import BetaRestore
from scripts.beta_release import BetaRelease


class BackupRehearsal:
    def __init__(self) -> None:
        self.deployment = DeploymentSmoke()
        self.restored: BetaRelease | None = None

    def run(self) -> None:
        host = self.deployment
        try:
            host.prepare()
            release = BetaRelease(host.manifest, host.project)
            release.activate(rollback=False)
            host.install_runtime_fixture()
            host.exercise_runs()
            host.compose(
                "stop", DeploymentService.RECOVERY, DeploymentService.API, fixture=True
            )
            database = ComposeDatabase(release)
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
            archive = BetaBackup(database, directory, recipients).create()
            BackupArchives(directory).require_recent()
            self.reject_invalid_database_dump(recipients, identity)
            restore = BetaRestore(host.manifest, archive, identity, host.directory)
            self.restored = BetaRelease(host.manifest, restore.project)
            project, seconds = restore.restore()
            restored_database = ComposeDatabase(self.restored)
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
                restored_database.release.command(
                    "ps", "--status", "running", "--services"
                ),
                env=restored_database.release.environment,
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
            if self.restored is not None:
                self.restored.compose("down", "--volumes", "--remove-orphans")
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
        failed_release = BetaRelease(self.deployment.manifest, restore.project)
        try:
            try:
                restore.restore()
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("invalid database dump reported restore success")
            database = ComposeDatabase(failed_release)
            running = subprocess.check_output(
                failed_release.command("ps", "--status", "running", "--services"),
                env=failed_release.environment,
                text=True,
            ).splitlines()
            assert set(running) == {POSTGRES_SERVICE, REDIS_SERVICE}
            assert self.sql(database, f"SELECT to_regclass('{USERS_TABLE}')") == ""
        finally:
            failed_release.compose("down", "--volumes", "--remove-orphans")
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
                ", ".join(
                    (
                        UserColumn.ID,
                        UserColumn.EMAIL,
                        UserColumn.PASSWORD_HASH,
                        UserColumn.CREATED_AT,
                    )
                )
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
            *database.release.command(
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
