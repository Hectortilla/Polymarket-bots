"""Retention and deletion acceptance uses real isolated PostgreSQL and Redis."""

import asyncio
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from api.auth.models import SessionRow, UserRow
from api.auth.passwords import hash_password
from api.auth.recovery.models import AccountTokenRow
from api.auth.recovery.policy import TokenPurpose
from api.auth.recovery.store import AccountCredentialStore
from api.auth.store import AuthStore
from api.bots.models import BotGraphRevisionRow, BotRow
from api.bots.store import BotStore
from api.catalog.definitions import CATALOG, NODE_BASED_DEFINITION_ID
from api.catalog.graphs.starter import STARTER_NODE_GRAPH
from api.events.contracts import RunLifecycleEvent, RunStatusPayload
from api.events.kinds import EventKind
from api.events.models import EventRow
from api.events.writer import RunEventWriter
from api.graph_templates.models import GraphTemplateRow
from api.lifecycle.audit import AuditRetention
from api.lifecycle.deletion.models import DeletionRequestRow
from api.lifecycle.deletion.purge import AccountPurger
from api.lifecycle.deletion.service import AccountDeletion
from api.lifecycle.history.purge import TerminalHistoryPurger
from api.lifecycle.history.retention import HistoryRetention
from api.lifecycle.maintenance import DataMaintenance
from api.lifecycle.policy import (
    CLEANUP_RUN_BATCH_SIZE,
    DELETION_QUIESCENCE_SECONDS,
    OPERATOR_AUDIT_RETENTION_DAYS,
)
from api.lifecycle.restoration import RestoreQuarantine
from api.limits.admission import RunAdmission
from api.limits.errors import ResourceLimitError
from api.limits.policy import PAPER_BETA
from api.limits.usage import AccountUsageReader
from api.operations.control import OperatorControl
from api.operations.models import OperatorAuditRow
from api.operations.schema import OperatorAction, OperatorOutcome
from api.operations.state import OperationControlStore
from api.runs.failures import ExecutionOwnershipLost, LaunchAttemptUnavailable
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from polybot.framework.clock import system_now_utc
from sqlalchemy import func, select

from control_plane.limits_fixtures import (
    account_bot,
    claim_run,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services

PASSWORD = "data lifecycle test password"


async def account_credentials(sessions):
    user, bot = await account_bot(sessions)
    async with sessions() as session:
        user = await AuthStore(session).find_user(user.email, lock=True)
        user.password_hash = await hash_password(PASSWORD)
        session.add(user)
        token = await AuthStore(session).issue_session(user, None)
    return user, bot, token


def test_retention_preserves_active_runs_account_boundaries_and_bots(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            first, first_bot = await account_bot(sessions)
            second, second_bot = await account_bot(sessions)
            active = await queue_run(sessions, first_bot)
            await claim_run(sessions, active)
            now = system_now_utc()
            cutoff = now - timedelta(days=PAPER_BETA.history_retention_days)
            async with sessions() as session:
                old = RunRow(
                    bot_id=first_bot.id,
                    definition_id=first_bot.definition_id,
                    config=first_bot.config.model_dump(mode="json"),
                    status=RunStatus.STOPPED,
                    created_at=cutoff - timedelta(hours=1),
                    ended_at=cutoff,
                )
                fresh = RunRow(
                    bot_id=second_bot.id,
                    definition_id=second_bot.definition_id,
                    config=second_bot.config.model_dump(mode="json"),
                    status=RunStatus.STOPPED,
                    ended_at=cutoff + timedelta(seconds=1),
                )
                session.add_all([old, fresh])
                await session.commit()
                assert await HistoryRetention(session).clean(now) == 1
                assert await HistoryRetention(session).clean(now) == 0
                assert await session.get(RunRow, old.id) is None
                assert await session.get(RunRow, fresh.id) is not None
                assert (
                    await session.get(RunRow, active.id)
                ).status is RunStatus.STARTING
                assert await session.get(BotRow, first_bot.id) is not None
                assert len(await RunStore(session).list_owned(second.id)) == 1

    asyncio.run(scenario())


def test_history_count_allowance_is_partitioned_by_account(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            first, first_bot = await account_bot(sessions)
            _, second_bot = await account_bot(sessions)
            now = system_now_utc()
            async with sessions() as session:
                rows = [
                    RunRow(
                        bot_id=first_bot.id,
                        definition_id=first_bot.definition_id,
                        config=first_bot.config.model_dump(mode="json"),
                        status=RunStatus.STOPPED,
                        created_at=now - timedelta(seconds=index),
                        ended_at=now,
                    )
                    for index in range(PAPER_BETA.retained_runs + 1)
                ]
                other = RunRow(
                    bot_id=second_bot.id,
                    definition_id=second_bot.definition_id,
                    config=second_bot.config.model_dump(mode="json"),
                    status=RunStatus.STOPPED,
                    created_at=now - timedelta(hours=1),
                    ended_at=now,
                )
                session.add_all([*rows, other])
                await session.commit()
                assert await HistoryRetention(session).clean(now) == 1
                assert await session.get(RunRow, rows[-1].id) is None
                assert await session.get(RunRow, other.id) is not None
                assert (
                    len(await RunStore(session).list_owned(first.id))
                    == PAPER_BETA.retained_runs
                )

    asyncio.run(scenario())


def test_partial_history_cleanup_is_hidden_atomic_and_retryable(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            now = system_now_utc()
            async with sessions() as session:
                run = RunRow(
                    bot_id=bot.id,
                    definition_id=bot.definition_id,
                    config=bot.config.model_dump(mode="json"),
                    status=RunStatus.STOPPED,
                    ended_at=now,
                )
                session.add(run)
                await session.flush()
                session.add_all(
                    [
                        EventRow(
                            run_id=run.id,
                            kind=EventKind.RUN_LIFECYCLE,
                            occurred_at=now,
                            payload={},
                        )
                        for _ in range(3)
                    ]
                )
                await session.commit()
                run_id = run.id
                with patch("api.lifecycle.history.purge.CLEANUP_EVENT_BATCH_SIZE", 2):
                    assert not await TerminalHistoryPurger(session).purge(run_id, now)
                    await session.rollback()
                    assert (
                        await session.scalar(select(func.count()).select_from(EventRow))
                        == 3
                    )
                    assert not await TerminalHistoryPurger(session).purge(run_id, now)
                    await session.commit()
                    assert await RunStore(session).read_owned(run_id, user.id) is None
                    assert await RunStore(session).list_owned(user.id) == ()
                    assert await TerminalHistoryPurger(session).purge(run_id, now)
                    await session.commit()
                assert await session.get(RunRow, run_id) is None
                assert (
                    await session.scalar(select(func.count()).select_from(EventRow))
                    == 0
                )

    asyncio.run(scenario())


def test_deletion_fences_jobs_preserves_other_accounts_and_cannot_be_resumed(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot, token = await account_credentials(sessions)
            other, other_bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            await claim_run(sessions, run)
            async with sessions() as session:
                await AccountDeletion(session).request(user.id, token, PASSWORD)
                assert await AuthStore(session).current_user(token) is None
                assert (
                    await RunStore(session).read(run.id)
                ).status is RunStatus.INTERRUPTED
                with pytest.raises(ValueError):
                    await OperatorControl(session, "fixture").apply(
                        OperatorAction.RESUME_ACCOUNT, user.id
                    )
                await session.rollback()
                assert await AccountPurger(session).clean(system_now_utc()) == 0
                later = system_now_utc() + timedelta(
                    seconds=DELETION_QUIESCENCE_SECONDS + 1
                )
                assert await AccountPurger(session).clean(later) == 1
                assert await AccountPurger(session).clean(later) == 0
                assert await session.get(UserRow, user.id) is None
                assert await session.get(BotRow, bot.id) is None
                assert await session.get(RunRow, run.id) is None
                assert (
                    await session.get(DeletionRequestRow, user.id)
                ).completed_at is not None
                assert await session.get(UserRow, other.id) is not None
                assert await session.get(BotRow, other_bot.id) is not None

    asyncio.run(scenario())


def test_restore_quarantine_blocks_old_sessions_jobs_and_unreviewed_access(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot, token = await account_credentials(sessions)
            suspended, _, _ = await account_credentials(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                await OperatorControl(session, "fixture").apply(
                    OperatorAction.SUSPEND, suspended.id
                )
                restore = RestoreQuarantine(session, "fixture")
                await restore.apply()
                original_marker = (
                    await session.get(UserRow, user.id)
                ).restore_quarantined_at
                await restore.apply()
                await session.refresh(await session.get(UserRow, user.id))
                assert (
                    await session.get(UserRow, user.id)
                ).restore_quarantined_at == original_marker
                assert (
                    await OperationControlStore(session).require()
                ).admissions_paused
                assert await AuthStore(session).current_user(token) is None
                assert (await session.get(UserRow, user.id)).access_allowed is False
                assert (
                    await RunStore(session).read(run.id)
                ).status is RunStatus.STOPPED
                with pytest.raises(ValueError):
                    await OperatorControl(session, "fixture").apply(
                        OperatorAction.RESUME_ACCOUNT, user.id
                    )
                await session.rollback()
                with pytest.raises(ValueError):
                    await restore.approve_account(suspended.id)
                await session.rollback()
                await restore.approve_account(user.id)
                assert (await session.get(UserRow, user.id)).access_allowed is True
                assert (
                    await RunStore(session).claim(run.id, now=system_now_utc()) is None
                )

    asyncio.run(scenario())


def test_deletion_serializes_with_launch_and_fences_delayed_writes(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot, token = await account_credentials(sessions)
            run = await queue_run(sessions, bot)
            claimed = await claim_run(sessions, run)
            async with sessions() as deletion:
                await RunAdmission(deletion).lock_transaction()
                launch = asyncio.create_task(queue_run(sessions, bot))
                await asyncio.sleep(0.03)
                assert not launch.done()
                await AccountDeletion(deletion).request(user.id, token, PASSWORD)
                with pytest.raises(ResourceLimitError):
                    await launch
                later = system_now_utc() + timedelta(
                    seconds=DELETION_QUIESCENCE_SECONDS + 1
                )
                assert await AccountPurger(deletion).clean(later) == 1
            writer = RunEventWriter(
                sessions, redis, execution_token=claimed.execution_token
            )
            with pytest.raises(ExecutionOwnershipLost):
                await writer.append(
                    RunLifecycleEvent(
                        run_id=run.id,
                        occurred_at=system_now_utc(),
                        payload=RunStatusPayload(status=RunStatus.RUNNING),
                    )
                )
            async with sessions() as session:
                assert await session.get(RunRow, run.id) is None
                assert (
                    await session.scalar(select(func.count()).select_from(EventRow))
                    == 0
                )

    asyncio.run(scenario())


def test_audit_retention_preserves_pending_deletions_and_recent_records(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            now = system_now_utc()
            cutoff = now - timedelta(days=OPERATOR_AUDIT_RETENTION_DAYS)
            async with sessions() as session:
                old = OperatorAuditRow(
                    actor="fixture",
                    action=OperatorAction.STOP_ALL,
                    outcome=OperatorOutcome.APPLIED,
                    occurred_at=cutoff,
                )
                fresh = OperatorAuditRow(
                    actor="fixture",
                    action=OperatorAction.STOP_ALL,
                    outcome=OperatorOutcome.APPLIED,
                    occurred_at=cutoff + timedelta(seconds=1),
                )
                pending = DeletionRequestRow(user_id=uuid4(), requested_at=cutoff)
                expired = DeletionRequestRow(
                    user_id=uuid4(), requested_at=cutoff, completed_at=cutoff
                )
                session.add_all([old, fresh, pending, expired])
                await session.commit()
                await AuditRetention(session).clean(now)
                assert await session.get(OperatorAuditRow, old.id) is None
                assert await session.get(OperatorAuditRow, fresh.id) is not None
                assert (
                    await session.get(DeletionRequestRow, pending.user_id) is not None
                )
                assert await session.get(DeletionRequestRow, expired.user_id) is None

    asyncio.run(scenario())


def test_restore_approval_requires_quarantine_pause_and_no_deletion_receipt(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, _, _ = await account_credentials(sessions)
            async with sessions() as session:
                restore = RestoreQuarantine(session, "fixture")
                with pytest.raises(ValueError):
                    await restore.approve_account(user.id)
                await session.rollback()
                await restore.apply()
                assert (
                    await OperationControlStore(session).require()
                ).admissions_paused
                session.add(DeletionRequestRow(user_id=user.id))
                await session.commit()
                before = await session.scalar(
                    select(func.count()).select_from(OperatorAuditRow)
                )
                with pytest.raises(ValueError):
                    await restore.approve_account(user.id)
                await session.rollback()
                assert (
                    await session.get(UserRow, user.id)
                ).restore_quarantined_at is not None
                assert (
                    await session.scalar(
                        select(func.count()).select_from(OperatorAuditRow)
                    )
                    == before
                )
                await session.delete(await session.get(DeletionRequestRow, user.id))
                await OperationControlStore(session).set_admissions_paused(False)
                await session.commit()
                with pytest.raises(ValueError):
                    await restore.approve_account(user.id)
                await session.rollback()
                await OperationControlStore(session).set_admissions_paused(True)
                await session.commit()
                await restore.approve_account(user.id)
                with pytest.raises(ValueError):
                    await restore.approve_account(user.id)

    asyncio.run(scenario())


def test_history_batch_boundaries_fallback_age_visibility_and_usage(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            active = await queue_run(sessions, bot)
            now = system_now_utc()
            cutoff = now - timedelta(days=PAPER_BETA.history_retention_days)
            async with sessions() as session:
                rows = [
                    RunRow(
                        bot_id=bot.id,
                        definition_id=bot.definition_id,
                        config=bot.config.model_dump(mode="json"),
                        status=RunStatus.STOPPED,
                        created_at=cutoff - timedelta(seconds=index),
                    )
                    for index in range(CLEANUP_RUN_BATCH_SIZE + 1)
                ]
                fresh = RunRow(
                    bot_id=bot.id,
                    definition_id=bot.definition_id,
                    config=bot.config.model_dump(mode="json"),
                    status=RunStatus.STOPPED,
                    created_at=cutoff + timedelta(hours=1),
                )
                session.add_all([*rows, fresh])
                session.add(
                    EventRow(
                        run_id=active.id,
                        kind=EventKind.RUN_LIFECYCLE,
                        occurred_at=now,
                        payload={},
                    )
                )
                await session.commit()
                assert not await TerminalHistoryPurger(session).purge(active.id, now)
                assert (await session.get(RunRow, active.id)).history_expired_at is None
                assert (
                    await session.scalar(select(func.count()).select_from(EventRow))
                    == 1
                )
                assert await RunStore(session).read_owned(rows[0].id, user.id) is None
                assert (
                    await AccountUsageReader(session, user.id).usage()
                ).retained_runs == 1
                assert (
                    await HistoryRetention(session).clean(now) == CLEANUP_RUN_BATCH_SIZE
                )
                assert await HistoryRetention(session).clean(now) == 1
                assert await session.get(RunRow, fresh.id) is not None

    asyncio.run(scenario())


def test_account_purge_batches_and_missing_identity_retry(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot, token = await account_credentials(sessions)
            now = system_now_utc()
            async with sessions() as session:
                session.add_all(
                    [
                        RunRow(
                            bot_id=bot.id,
                            definition_id=bot.definition_id,
                            config=bot.config.model_dump(mode="json"),
                            status=RunStatus.STOPPED,
                        )
                        for _ in range(CLEANUP_RUN_BATCH_SIZE + 1)
                    ]
                )
                await session.commit()
                await AccountDeletion(session).request(user.id, token, PASSWORD)
                later = now + timedelta(seconds=DELETION_QUIESCENCE_SECONDS + 2)
                assert await AccountPurger(session).clean(later) == 0
                assert await session.get(UserRow, user.id) is not None
                assert await AccountPurger(session).clean(later) == 1
                missing_user = uuid4()
                session.add(DeletionRequestRow(user_id=missing_user, requested_at=now))
                await session.commit()
                assert await AccountPurger(session).clean(later) == 1
                assert (
                    await session.get(DeletionRequestRow, missing_user)
                ).completed_at is not None

    asyncio.run(scenario())


def test_maintenance_erases_every_owned_dependency_and_preserves_foreign_rows(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            owner, _, token = await account_credentials(sessions)
            other, _, other_token = await account_credentials(sessions)
            graphs, templates, links = {}, {}, {}
            for user in (owner, other):
                async with sessions() as session:
                    graphs[user.id] = await BotStore(session, user.id).create(
                        definition_id=NODE_BASED_DEFINITION_ID,
                        config=CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
                            {"name": "deletion graph", "market_slugs": ["fixture"]}
                        ),
                        graph=STARTER_NODE_GRAPH,
                    )
                    template = GraphTemplateRow(
                        owner_user_id=user.id,
                        name="private fixture",
                        graph=STARTER_NODE_GRAPH.model_dump(mode="json"),
                    )
                    session.add(template)
                    await session.commit()
                    templates[user.id] = template.id
                    links[user.id] = await AccountCredentialStore(session).issue_link(
                        user.email, TokenPurpose.RESET
                    )
                run = await queue_run(sessions, graphs[user.id])
                async with sessions() as session:
                    await RunStore(session).request_stop(run.id, now=system_now_utc())
            async with sessions() as session:
                await AccountDeletion(session).request(owner.id, token, PASSWORD)
                receipt = await session.get(DeletionRequestRow, owner.id)
                receipt.requested_at -= timedelta(
                    seconds=DELETION_QUIESCENCE_SECONDS + 1
                )
                session.add(receipt)
                await session.commit()
            await DataMaintenance(sessions).tick()
            async with sessions() as session:
                assert await session.get(UserRow, owner.id) is None
                assert await session.get(BotRow, graphs[owner.id].id) is None
                assert (
                    await session.get(
                        BotGraphRevisionRow, graphs[owner.id].latest_graph_revision.id
                    )
                    is None
                )
                assert await session.get(GraphTemplateRow, templates[owner.id]) is None
                assert (
                    await session.get(AccountTokenRow, links[owner.id].digest) is None
                )
                assert await session.get(SessionRow, token.digest) is None
                assert await session.get(UserRow, other.id) is not None
                assert (
                    await session.get(
                        BotGraphRevisionRow, graphs[other.id].latest_graph_revision.id
                    )
                    is not None
                )
                assert (
                    await session.get(GraphTemplateRow, templates[other.id]) is not None
                )
                assert (
                    await session.get(AccountTokenRow, links[other.id].digest)
                    is not None
                )
                assert await AuthStore(session).current_user(other_token) is not None

    asyncio.run(scenario())


def test_expired_or_missing_launch_recovery_never_creates_a_replacement(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            owner, bot = await account_bot(sessions)
            key = uuid4()
            async with sessions() as session:
                store = RunStore(session)
                run = await store.create_from_bot(bot, launch_key=key)
                assert (await store.recover_existing_launch(bot.id, key)).id == run.id
                await store.request_stop(run.id, now=system_now_utc())
                row = await session.get(RunRow, run.id)
                row.history_expired_at = system_now_utc()
                session.add(row)
                await session.commit()
                with pytest.raises(LaunchAttemptUnavailable):
                    await store.read_launch(bot.id, key)
                await session.rollback()
                assert await TerminalHistoryPurger(session).purge(
                    run.id, system_now_utc()
                )
                await session.commit()
                with pytest.raises(LaunchAttemptUnavailable):
                    await store.recover_existing_launch(bot.id, key)
                await session.rollback()
                assert (
                    await session.scalar(select(func.count()).select_from(RunRow)) == 0
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("retention", ["retained", "age", "count"])
def test_terminal_launch_recovery_uses_unmarked_history_policy(
    limits_services, retention
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            owner, bot = await account_bot(sessions)
            now = system_now_utc()
            key = uuid4()
            async with sessions() as session:
                row = RunRow(
                    bot_id=bot.id,
                    definition_id=bot.definition_id,
                    config=bot.config.model_dump(mode="json"),
                    status=RunStatus.STOPPED,
                    launch_key=key,
                    created_at=now - timedelta(seconds=1),
                    ended_at=now,
                )
                if retention == "age":
                    row.ended_at = now - timedelta(
                        days=PAPER_BETA.history_retention_days, seconds=1
                    )
                session.add(row)
                if retention == "count":
                    session.add_all(
                        [
                            RunRow(
                                bot_id=bot.id,
                                definition_id=bot.definition_id,
                                config=bot.config.model_dump(mode="json"),
                                status=RunStatus.STOPPED,
                                created_at=now,
                                ended_at=now,
                            )
                            for _ in range(PAPER_BETA.retained_runs)
                        ]
                    )
                await session.commit()
                store = RunStore(session)
                if retention == "retained":
                    assert (
                        await store.recover_existing_launch(bot.id, key)
                    ).id == row.id
                else:
                    with pytest.raises(LaunchAttemptUnavailable):
                        await store.recover_existing_launch(bot.id, key)
                assert row.history_expired_at is None

    asyncio.run(scenario())
