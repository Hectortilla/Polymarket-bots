"""Private maintenance CLI validation, dispatch, redaction and resource cleanup."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from api.deployment.settings import StartupSettings
from api.lifecycle import __main__ as lifecycle_cli
from api.lifecycle import runtime
from api.lifecycle.commands import (
    LIFECYCLE_MODULE,
    RESTORE_RECONCILIATION_FLAG,
    DataCommand,
)

from scripts.beta_backup import __main__ as backup_cli
from scripts.beta_backup.commands import BackupCommand


@pytest.mark.parametrize("command", list(DataCommand))
def test_lifecycle_cli_dispatches_validated_command(monkeypatch, command):
    user_id = uuid4()
    arguments = [LIFECYCLE_MODULE, command]
    if command is DataCommand.APPROVE_RESTORED_ACCOUNT:
        arguments.extend([str(user_id), RESTORE_RECONCILIATION_FLAG])
    monkeypatch.setattr("sys.argv", arguments)
    settings = StartupSettings(database_url="fixture", redis_url="fixture")
    with (
        patch.object(lifecycle_cli.StartupSettings, "from_env", return_value=settings),
        patch.object(lifecycle_cli, "execute", new_callable=AsyncMock) as execute,
    ):
        lifecycle_cli.main()
    execute.assert_awaited_once()
    assert execute.await_args.args[:3] == (
        command,
        user_id if command is DataCommand.APPROVE_RESTORED_ACCOUNT else None,
        settings,
    )


def test_restore_approval_cli_requires_explicit_reconciliation(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [LIFECYCLE_MODULE, DataCommand.APPROVE_RESTORED_ACCOUNT, str(uuid4())],
    )
    with pytest.raises(SystemExit) as error:
        lifecycle_cli.main()
    assert error.value.code == 2


def test_lifecycle_cli_redacts_failure_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", [LIFECYCLE_MODULE, DataCommand.CLEAN])
    with patch.object(
        lifecycle_cli.StartupSettings,
        "from_env",
        side_effect=RuntimeError("private fixture secret"),
    ):
        with pytest.raises(SystemExit) as error:
            lifecycle_cli.main()
    assert error.value.code == 1
    assert "private fixture secret" not in capsys.readouterr().err


@pytest.mark.parametrize("command", list(DataCommand))
@pytest.mark.parametrize("fails", [False, True])
def test_lifecycle_runtime_dispatch_and_database_disposal(command, fails):
    async def scenario():
        engine = AsyncMock()
        sessions = MagicMock()
        maintenance = AsyncMock()
        restore = AsyncMock()
        operation = (
            maintenance.tick
            if command is DataCommand.CLEAN
            else restore.apply
            if command is DataCommand.QUARANTINE_RESTORE
            else restore.approve_account
        )
        if fails:
            operation.side_effect = RuntimeError("fixture failure")
        user_id = uuid4()
        with (
            patch.object(runtime, "DeploymentSchema") as schema,
            patch.object(
                runtime, "create_worker_database", return_value=(engine, sessions)
            ),
            patch.object(runtime, "DataMaintenance", return_value=maintenance),
            patch.object(runtime, "RestoreQuarantine", return_value=restore),
        ):
            schema.return_value.require_compatible = AsyncMock()
            if fails:
                with pytest.raises(RuntimeError):
                    await runtime.execute(
                        command,
                        user_id,
                        StartupSettings(database_url="fixture", redis_url="fixture"),
                        "fixture",
                    )
            else:
                await runtime.execute(
                    command,
                    user_id,
                    StartupSettings(database_url="fixture", redis_url="fixture"),
                    "fixture",
                )
            operation.assert_awaited_once()
            engine.dispose.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("command", list(BackupCommand))
def test_backup_cli_dispatch(monkeypatch, command):
    arguments = ["backup", command]
    if command is BackupCommand.CREATE:
        arguments += [
            "manifest",
            "--directory",
            "backup-directory",
            "--recipients",
            "recipients",
        ]
    elif command is BackupCommand.CHECK:
        arguments += ["--directory", "backup-directory"]
    else:
        arguments += [
            "manifest",
            "archive",
            "--identity",
            "identity",
            "--scratch-directory",
            "scratch",
        ]
    monkeypatch.setattr("sys.argv", arguments)
    with (
        patch.object(backup_cli, "BetaRelease"),
        patch.object(backup_cli, "ComposeDatabase"),
        patch.object(backup_cli, "BetaBackup") as backup,
        patch.object(backup_cli, "BackupArchives") as archives,
        patch.object(backup_cli, "BetaRestore") as restore,
    ):
        backup.return_value.create.return_value = Path("archive")
        restore.return_value.restore.return_value = ("isolated", 1.0)
        backup_cli.main()
        if command is BackupCommand.CREATE:
            backup.return_value.create.assert_called_once()
        elif command is BackupCommand.CHECK:
            archives.return_value.require_recent.assert_called_once()
        else:
            restore.return_value.restore.assert_called_once()
