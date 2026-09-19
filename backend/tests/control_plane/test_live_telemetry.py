"""Regression coverage at real SQL, Redis, mailbox and clock boundaries."""

import asyncio
import os
from dataclasses import replace
from datetime import timedelta
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
from api.events.channels import run_event_channel
from api.events.contracts import LiveRunSnapshot, StreamHealthEvent
from api.events.contracts.payloads.chart import EquityChartPointPayload
from api.events.contracts.payloads.lifecycle import FeedObservation
from api.events.health.policy import FEED_TTL_SECONDS
from api.events.health.store import FeedHealthStore
from api.events.live.clock import ClockUnavailable, ShardClock
from api.events.live.contracts import LivePermit, PublishedSnapshot
from api.events.live.metrics import LiveMetric, LiveMetrics
from api.events.live.permits import LivePermitRefresher
from api.events.live.policy import (
    LIVE_CLOCK_DRIFT_SECONDS,
    LIVE_MAX_IN_FLIGHT_PER_SHARD,
    LIVE_PERMIT_SECONDS,
    LIVE_REFRESH_BATCH_SIZE,
)
from api.events.live.redis import LiveRedisBoundary
from api.events.live.routing import LIVE_CHANNEL_PREFIX, LiveShardRouter
from api.events.live.service import WorkerLiveTelemetry
from api.events.observer import WebRuntimeObserver
from api.events.terminal_wakes import _SINK_KEY, TerminalWakePublisher
from api.http.sse.hub import LiveSubscriptionHub
from api.http.sse.mailbox import LiveFrame, ViewerMailbox
from api.http.sse.subscriptions import SubscriptionLane
from api.operations.control import OperatorControl
from api.operations.observations.sink import OPERATION_LOG
from api.operations.schema import OperatorAction
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.models import RunRow
from api.runs.status import RunStatus
from polybot.cli.observability.events import StreamHealth
from polybot.framework.clock import system_now_ms, system_now_utc
from polybot.performance.contracts.valuation_status import ValuationStatus
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.orm import Session

from control_plane.disposable_services import disposable_redis_url
from control_plane.limits_fixtures import (
    account_bot,
    claim_run,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services
from control_plane.service_config import TEST_SECOND_REDIS_URL_ENV


def snapshot(run_id, *, generation=1, sequence=1):
    return LiveRunSnapshot(
        run_id=run_id,
        occurred_at=system_now_utc(),
        generation=generation,
        sequence=sequence,
        sampled_at_ms=system_now_ms(),
        markets=(),
        equity=EquityChartPointPayload(value="1", status=ValuationStatus.FRESH),
    )


async def eventually(predicate, seconds=3):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.01)


def test_router_parses_only_its_channel_and_shard():
    router = LiveShardRouter(("redis://one", "redis://two"))
    run = uuid4()
    shard = router.shard_for(run).index
    assert router.channel(run).startswith(LIVE_CHANNEL_PREFIX)
    assert router.run_from_channel(router.channel(run).encode(), shard) == run
    assert router.run_from_channel(router.channel(run), 1 - shard) is None
    assert router.run_from_channel(b"bad", shard) is None
    assert "redis://" not in repr(router.shard_for(run))


def test_clock_uses_sampling_start_and_invalidates_discontinuity():
    async def scenario():
        now = [10.0]
        clock = ShardClock(now=lambda: now[0])

        class Redis:
            async def time(self):
                now[0] += 0.2
                return 100, 0

        sample = await clock.sample(Redis())
        assert sample.deadline(LIVE_PERMIT_SECONDS) <= 104_750_000
        assert clock.fresh(sample.deadline(LIVE_PERMIT_SECONDS))
        now[0] += 6
        assert not clock.fresh(sample.deadline(LIVE_PERMIT_SECONDS))
        with pytest.raises(ClockUnavailable):
            await clock.sample(Redis())
        assert clock.epoch == 1
        assert not clock.fresh(1_000_000_000)

    asyncio.run(scenario())


def test_slow_time_reply_cannot_mint_authority():
    async def scenario():
        now = [0.0]
        clock = ShardClock(now=lambda: now[0])

        class Redis:
            async def time(self):
                now[0] += 1
                return 100, 0

        with pytest.raises(ClockUnavailable):
            await clock.sample(Redis())
        assert clock.epoch == 1

    asyncio.run(scenario())


def test_clock_invalidation_during_time_request_rejects_late_mapping():
    async def scenario():
        clock = ShardClock()

        class Redis:
            async def time(self):
                clock.invalidate()
                return 100, 0

        with pytest.raises(ClockUnavailable):
            await clock.sample(Redis())
        assert not clock.fresh(200_000_000)

    asyncio.run(scenario())


def test_clock_invalidation_during_sql_cannot_mint_a_new_epoch_permit():
    async def scenario():
        run, token = uuid4(), uuid4()
        clock = ShardClock()

        class Session:
            def __call__(self):
                return self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute(self, statement):
                clock.invalidate()
                return SimpleNamespace(
                    all=lambda: [SimpleNamespace(id=run, execution_token=token)]
                )

        class Redis:
            async def time(self):
                return 100, 0

        refresher = LivePermitRefresher(
            Session(),
            LiveShardRouter(("redis://fixture",)),
            (Redis(),),
            lease_seconds=DEFAULT_LEASE_SECONDS,
            clocks=(clock,),
        )
        registration = refresher.register(run, token)
        await refresher.refresh_once()
        assert refresher.permit_for(registration) is None

    asyncio.run(scenario())


def test_subscription_lane_does_not_scan_all_channels_per_frame():
    async def scenario():
        delivered = []
        done = asyncio.Event()

        class CountedSet(set):
            copies = 0

            def copy(self):
                self.copies += 1
                return super().copy()

        class PubSub:
            def __init__(self):
                self.acknowledgements = []

            async def subscribe(self, *channels):
                self.acknowledgements.extend(channels)

            async def get_message(self, **kwargs):
                await asyncio.sleep(0)
                if self.acknowledgements:
                    return {
                        "type": "subscribe",
                        "channel": self.acknowledgements.pop().encode(),
                    }
                return {"type": "message", "channel": b"run:1", "data": b"1"}

            async def aclose(self):
                pass

        def receive(message):
            delivered.append(message)
            if len(delivered) == 100:
                done.set()

        lane = SubscriptionLane(
            SimpleNamespace(pubsub=PubSub), receive, lambda: None, LiveMetrics()
        )
        lane._desired = CountedSet()
        for index in range(1000):
            lane.add(f"run:{index}")
        lane.start()
        try:
            await asyncio.wait_for(done.wait(), 2)
            assert lane._desired.copies == 1
            assert all(message["type"] == "message" for message in delivered)
        finally:
            await lane.close()

    asyncio.run(scenario())


def test_unregister_and_slow_query_cannot_resurrect_permits():
    async def scenario():
        now = [0.0]
        run, token = uuid4(), uuid4()
        entered, release = asyncio.Event(), asyncio.Event()

        class Session:
            def __call__(self):
                return self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute(self, statement):
                entered.set()
                await release.wait()
                return SimpleNamespace(
                    all=lambda: [SimpleNamespace(id=run, execution_token=token)]
                )

        class Redis:
            async def time(self):
                return 100 + int(now[0]), 0

        refresher = LivePermitRefresher(
            Session(),
            LiveShardRouter(("redis://fixture",)),
            (Redis(),),
            lease_seconds=DEFAULT_LEASE_SECONDS,
            now=lambda: now[0],
        )
        registration = refresher.register(run, token)
        task = asyncio.create_task(refresher.refresh_once())
        await entered.wait()
        refresher.unregister(run, registration.registration)
        replacement = refresher.register(run, token)
        release.set()
        await task
        assert refresher.permit_for(replacement) is None
        now[0] = 6
        # A query whose time advances past the immutable start deadline is rejected.
        release.clear()
        entered.clear()
        task = asyncio.create_task(refresher.refresh_once())
        await entered.wait()
        now[0] = 12
        release.set()
        await task
        assert refresher.permit_for(replacement) is None

    asyncio.run(scenario())


def test_mailbox_expiry_and_terminal_drop_pending_live():
    async def scenario():
        clock = SimpleNamespace(epoch=1, fresh=lambda _: True)
        mailbox = ViewerMailbox()
        first, latest = (
            LiveFrame(value, 1, clock, 1) for value in (b"first", b"latest")
        )
        mailbox.offer_live(first)
        mailbox.offer_live(latest)
        mailbox.offer_durable_wake()
        assert await mailbox.next() == (latest, True, False)
        mailbox.offer_live(first)
        clock.epoch = 2
        mailbox.offer_durable_wake()
        assert await mailbox.next() == (None, True, False)
        mailbox.terminal()
        mailbox.offer_live(latest)
        assert await mailbox.next() == (None, True, False)

    asyncio.run(scenario())


def test_snapshot_rejects_markers_duplicates_and_unknown_fields():
    raw = snapshot(uuid4()).model_dump(mode="json")
    point = dict(token_id="a", label="A", value="0.5", status="fresh", markers=[])
    for update in (
        {"markets": [dict(point, markers=["BUY"])]},
        {"markets": [dict(point, token_id=" ")]},
        {"markets": [dict(point, label=" ")]},
        {"sampled_at_ms": 2**53},
        {"markets": [point, point]},
        {"id": 1},
        {"generation": 0},
    ):
        with pytest.raises(ValidationError):
            LiveRunSnapshot.model_validate(raw | update)


def test_real_permit_query_batches_and_refuses_wrong_tokens(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await claim_run(sessions, await queue_run(sessions, bot))
            refresher = LivePermitRefresher(
                sessions,
                LiveShardRouter(("redis://fixture",)),
                (redis,),
                lease_seconds=DEFAULT_LEASE_SECONDS,
            )
            correct = refresher.register(run.id, run.execution_token)
            for _ in range(LIVE_REFRESH_BATCH_SIZE):
                refresher.register(uuid4(), uuid4())
            await refresher.refresh_once()
            permit = refresher.permit_for(correct)
            assert (
                permit is not None
                and permit.local_deadline <= monotonic() + LIVE_PERMIT_SECONDS
            )
            assert refresher.metrics.snapshot()[LiveMetric.SQL_QUERIES] == 2
            wrong = refresher.register(run.id, uuid4())
            await refresher.refresh_once()
            assert refresher.permit_for(wrong) is None
            assert refresher.permit_for(correct) is None

    asyncio.run(scenario())


def test_redis_scripts_deadlines_noscript_and_health_ordering(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (_, redis):
            router = LiveShardRouter(("redis://fixture",))
            clock = ShardClock()
            sample = await clock.sample(redis)
            permit = LivePermit(
                uuid4(),
                1,
                0,
                monotonic() + LIVE_PERMIT_SECONDS,
                sample.deadline(LIVE_PERMIT_SECONDS),
                clock.epoch,
            )
            boundary = LiveRedisBoundary(router, (redis,), (clock,))
            assert await boundary.publish(
                permit, b"{}"
            )  # zero subscribers is successful
            await redis.script_flush()
            assert await boundary.publish(permit, b"{}")
            expired = replace(permit, redis_deadline_us=1)
            assert not await boundary.publish(expired, b"{}")
            store = FeedHealthStore(router, (redis,))
            now = system_now_utc()
            observation = FeedObservation.from_observation(
                StreamHealth(0, 0, 0), observed_at=now - timedelta(seconds=10)
            )
            assert await store.record(permit, observation, 1, clock)
            ttl = await redis.pttl(store.key(permit.run_id))
            assert (
                (FEED_TTL_SECONDS - 11) * 1000
                < ttl
                <= (FEED_TTL_SECONDS - 10 + LIVE_CLOCK_DRIFT_SECONDS) * 1000
            )
            before = await redis.get(store.key(permit.run_id))
            older = observation.model_copy(
                update={"observed_at": now - timedelta(seconds=20)}
            )
            assert not await store.record(permit, older, 2, clock)
            assert not await store.record(permit, observation, 3, clock)
            assert await redis.get(store.key(permit.run_id)) == before
            assert await redis.pttl(store.key(permit.run_id)) <= ttl
            newer = observation.model_copy(
                update={"observed_at": now - timedelta(seconds=5)}
            )
            assert await store.record(replace(permit, registration=2), newer, 1, clock)
            assert not await store.record(
                permit, observation.model_copy(update={"observed_at": now}), 10, clock
            )
            assert not await store.record(expired, newer, 20, clock)
            for invalid in ("[]", "42", "{", '{"observation": {}}'):
                await redis.set(store.key(permit.run_id), invalid)
                assert await store.read(permit.run_id) is None
            await redis.delete(store.key(permit.run_id))

    asyncio.run(scenario())


def test_real_hub_idle_start_multiplexes_validates_and_recovers(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (_, redis):
            router = LiveShardRouter(("redis://fixture",))
            hub = LiveSubscriptionHub(router, (redis,), redis)
            await hub.start()
            await asyncio.sleep(0.15)  # no subscriptions yet: readers must survive
            run = uuid4()
            try:
                viewers = await asyncio.gather(*(hub.attach(run) for _ in range(10)))
                boundary = LiveRedisBoundary(router, (redis,), (ShardClock(),))
                counts = await boundary.subscriber_counts(0, (router.channel(run),))
                assert counts[router.channel(run)] == 1
                clock = hub._clocks[0]
                sample = await clock.sample(redis)

                def frame(sequence=1, target=run):
                    return PublishedSnapshot(
                        snapshot=snapshot(target, sequence=sequence),
                        publication_deadline_us=sample.deadline(LIVE_PERMIT_SECONDS),
                    ).model_dump_json()

                await redis.publish(router.channel(run), frame(target=uuid4()))
                await redis.publish(router.channel(run), frame())
                received = await asyncio.wait_for(
                    asyncio.gather(*(viewer.next() for viewer in viewers)), 2
                )
                assert all(
                    item[0] is received[0][0] for item in received
                )  # encode once, shared bytes
                await redis.publish(router.channel(run), frame())  # duplicate
                await redis.publish(router.channel(run), frame(2))
                assert (
                    b'"sequence":2'
                    in (await asyncio.wait_for(viewers[0].next(), 2))[0].data
                )
                # Other viewers still have sequence 2 queued when the connection dies.
                assert viewers[1]._live is not None
                await redis.client_kill_filter(_type="pubsub")
                await eventually(
                    lambda: hub.metrics.snapshot().get(LiveMetric.RECONNECT, 0) >= 2
                )
                assert viewers[1]._live is None
                await asyncio.sleep(0.3)
                await clock.sample(redis)
                await redis.publish(router.channel(run), frame(3))
                while True:
                    value, _, _ = await asyncio.wait_for(viewers[0].next(), 2)
                    if value is not None:
                        break
                assert b'"sequence":3' in value.data
                hub.terminal(run)
                hub._receive_live(0, {"channel": router.channel(run), "data": frame(4)})
                assert all(viewer._live is None for viewer in viewers)
                assert (await viewers[0].next())[0] is None
                for viewer in viewers:
                    await hub.detach(run, viewer)
                assert not hub._viewers and not hub._identities and not hub._terminal
            finally:
                await hub.close()

    asyncio.run(scenario())


def test_failed_attach_rolls_back_viewer_registration(limits_services, monkeypatch):
    async def scenario():
        async with resource_services(limits_services) as (_, redis):
            hub = LiveSubscriptionHub(
                LiveShardRouter(("redis://fixture",)), (redis,), redis
            )

            async def fail(*args):
                raise TimeoutError()

            monkeypatch.setattr(SubscriptionLane, "ready", fail)
            await hub.start()
            try:
                with pytest.raises(TimeoutError):
                    await hub.attach(uuid4())
                assert not hub._viewers
                assert not hub._durable.watching and not hub._live[0].watching
            finally:
                await hub.close()

    asyncio.run(scenario())


def test_publisher_coalesces_with_fixed_workers_and_no_per_frame_sql(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await claim_run(sessions, await queue_run(sessions, bot))
            router = LiveShardRouter(("redis://fixture",))
            hub = LiveSubscriptionHub(router, (redis,), redis)
            live = WorkerLiveTelemetry(
                sessions, router, (redis,), lease_seconds=DEFAULT_LEASE_SECONDS
            )
            handle = live.for_execution(run.id, run.execution_token)
            await hub.start()
            try:
                mailbox = await hub.attach(run.id)
                await hub._clocks[0].sample(redis)
                await live.permits.refresh_once()
                await live.publisher.refresh_interest_once(0)
                registration = handle._registration
                assert handle.watched()
                for sequence in range(1, 1001):
                    assert live.publisher.submit(
                        registration,
                        snapshot(
                            run.id,
                            generation=registration.registration,
                            sequence=sequence,
                        ),
                    )
                live.publisher.measure_slots()
                assert live.metrics.snapshot()[LiveMetric.PENDING] == 1
                queries = live.metrics.snapshot()[LiveMetric.SQL_QUERIES]
                await live.publisher.start()
                received = (await asyncio.wait_for(mailbox.next(), 2))[0]
                assert b'"sequence":1000' in received.data
                assert live.metrics.snapshot()[LiveMetric.SQL_QUERIES] == queries
                assert len(live.publisher._workers) == LIVE_MAX_IN_FLIGHT_PER_SHARD + 1
                assert live.metrics.snapshot()[LiveMetric.COALESCED] == 999
                handle.close()
                assert not live.publisher._slots and not live.permits._registrations
            finally:
                await live.close()
                await hub.close()

    asyncio.run(scenario())


def test_terminal_operator_wake_is_postcommit(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            sink = TerminalWakePublisher(sessions, redis)
            pubsub = redis.pubsub()
            await pubsub.subscribe(run_event_channel(run.id))
            await pubsub.get_message(timeout=1)
            await sink.start()
            try:
                async with sessions() as session:
                    await OperatorControl(session, "fixture").apply(
                        OperatorAction.STOP_RUN, run.id
                    )
                async with asyncio.timeout(2):
                    while True:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=0.1
                        )
                        if message:
                            break
                assert int(message["data"]) > 0
            finally:
                await sink.close()
                await pubsub.aclose()

    asyncio.run(scenario())


def test_savepoint_commit_does_not_publish_and_rollback_preserves_outer_wakes():
    accepted = []
    session = Session(info={_SINK_KEY: SimpleNamespace(offer=accepted.append)})
    run = uuid4()
    session.begin()
    TerminalWakePublisher.stage(session, run, 1)
    nested = session.begin_nested()
    TerminalWakePublisher.stage(session, run, 2)
    nested.rollback()
    nested = session.begin_nested()
    TerminalWakePublisher.stage(session, run, 3)
    nested.commit()
    assert accepted == []
    session.commit()
    assert accepted == [(run, 1), (run, 3)]
    session.begin()
    TerminalWakePublisher.stage(session, run, 4)
    session.rollback()
    assert accepted == [(run, 1), (run, 3)]
    session.close()


def test_session_close_discards_uncommitted_terminal_wakes_before_reuse():
    accepted = []
    session = Session(info={_SINK_KEY: SimpleNamespace(offer=accepted.append)})
    run = uuid4()
    session.begin()
    TerminalWakePublisher.stage(session, run, 1)
    session.close()
    session.begin()
    TerminalWakePublisher.stage(session, run, 2)
    session.commit()
    assert accepted == [(run, 2)]
    session.close()


def test_observer_health_without_viewers_keeps_observation_age(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await claim_run(sessions, await queue_run(sessions, bot))
            router = LiveShardRouter(("redis://fixture",))
            live = WorkerLiveTelemetry(
                sessions, router, (redis,), lease_seconds=DEFAULT_LEASE_SECONDS
            )
            handle = live.for_execution(run.id, run.execution_token)
            observed_at = system_now_utc() - timedelta(seconds=20)
            written = []

            class Writer:
                async def append(self, event):
                    written.append(event)

            observer = WebRuntimeObserver(
                run.id, Writer(), live_telemetry=handle, now_utc=lambda: observed_at
            )
            store = FeedHealthStore(router, (redis,))
            try:
                await live.permits.refresh_once()
                queries = live.metrics.snapshot()[LiveMetric.SQL_QUERIES]
                await live.publisher.start()
                await observer.start(bot.config)
                observer.emit(StreamHealth(0, 0, 0))
                await eventually(
                    lambda: live.metrics.snapshot().get(LiveMetric.HEALTH_WRITTEN) == 1
                )
                assert not handle.watched()
                assert await store.read(run.id) is not None
                assert (
                    0
                    < await redis.pttl(store.key(run.id))
                    < (FEED_TTL_SECONDS - 20 + LIVE_CLOCK_DRIFT_SECONDS) * 1000
                )
                assert live.metrics.snapshot()[LiveMetric.SQL_QUERIES] == queries
                await observer.stop()
                health_events = [
                    event for event in written if isinstance(event, StreamHealthEvent)
                ]
                assert health_events[0].occurred_at == observed_at
                assert handle._closed and not live.permits._registrations
            finally:
                await observer.stop()
                await live.close()

    asyncio.run(scenario())


def test_inflight_publication_keeps_original_permit_and_latest_pending(
    limits_services, monkeypatch
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await claim_run(sessions, await queue_run(sessions, bot))
            router = LiveShardRouter(("redis://fixture",))
            live = WorkerLiveTelemetry(
                sessions, router, (redis,), lease_seconds=DEFAULT_LEASE_SECONDS
            )
            handle = live.for_execution(run.id, run.execution_token)
            registration = handle._registration
            slot = live.publisher._slots[run.id]
            pubsub = redis.pubsub()
            await pubsub.subscribe(router.channel(run.id))
            await pubsub.get_message(timeout=1)
            entered, release = asyncio.Event(), asyncio.Event()
            sent, health = [], []
            original_publish = LiveRedisBoundary.publish
            original_record = FeedHealthStore.record

            async def delayed(boundary, permit, payload):
                sent.append((permit, PublishedSnapshot.model_validate_json(payload)))
                if len(sent) == 1:
                    entered.set()
                    await release.wait()
                return await original_publish(boundary, permit, payload)

            async def record(store, permit, observation, sequence, clock):
                health.append(observation)
                return await original_record(
                    store, permit, observation, sequence, clock
                )

            monkeypatch.setattr(LiveRedisBoundary, "publish", delayed)
            monkeypatch.setattr(FeedHealthStore, "record", record)
            try:
                await live.permits.refresh_once()
                await live.publisher.refresh_interest_once(0)
                old = live.permits.permit_for(registration)
                assert live.publisher.submit(
                    registration, snapshot(run.id, generation=registration.registration)
                )
                await live.publisher.start()
                await asyncio.wait_for(entered.wait(), 2)
                await live.permits.refresh_once()
                renewed = live.permits.permit_for(registration)
                assert renewed.redis_deadline_us > old.redis_deadline_us
                for sequence in (2, 3):
                    live.publisher.submit(
                        registration,
                        snapshot(
                            run.id,
                            generation=registration.registration,
                            sequence=sequence,
                        ),
                    )
                now = system_now_utc()
                observations = [
                    FeedObservation.from_observation(
                        StreamHealth(0, 0, 0),
                        observed_at=now - timedelta(seconds=seconds),
                    )
                    for seconds in (3, 1, 2)
                ]
                assert live.publisher.submit_health(registration, observations[0], 1)
                assert live.publisher.submit_health(registration, observations[1], 2)
                assert not live.publisher.submit_health(
                    registration, observations[2], 3
                )
                live.publisher.measure_slots()
                assert live.metrics.snapshot()[LiveMetric.PENDING] == 1
                assert live.metrics.snapshot()[LiveMetric.PENDING_HEALTH] == 1
                assert slot.inflight
                release.set()
                await eventually(
                    lambda: len(sent) == 2 and len(health) == 1 and not slot.inflight
                )
                assert [frame.snapshot.sequence for _, frame in sent] == [1, 3]
                assert sent[0][0] is old
                assert sent[0][1].publication_deadline_us == old.redis_deadline_us
                assert sent[1][0] is renewed
                assert health == [observations[1]]
            finally:
                release.set()
                handle.close()
                await live.close()
                await pubsub.aclose()

    asyncio.run(scenario())


def test_terminal_wake_failure_does_not_rollback_committed_stop(
    limits_services, monkeypatch
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            failures = []

            async def fail_publish(*args, **kwargs):
                raise ConnectionError("injected redis outage")

            monkeypatch.setattr(redis, "publish", fail_publish)
            monkeypatch.setattr(OPERATION_LOG, "emit", failures.append)
            sink = TerminalWakePublisher(sessions, redis)
            await sink.start()
            try:
                async with sessions() as session:
                    await OperatorControl(session, "fixture").apply(
                        OperatorAction.STOP_RUN, run.id
                    )
                await asyncio.wait_for(sink._pending.join(), 2)
                async with sessions() as session:
                    assert (
                        await session.get(RunRow, run.id)
                    ).status == RunStatus.STOPPED
                assert failures
            finally:
                await sink.close()

    asyncio.run(scenario())


def test_two_real_shards_route_health_and_isolate_disconnects(limits_services):
    second_url = os.getenv(TEST_SECOND_REDIS_URL_ENV)
    if second_url is None:
        pytest.skip(f"{TEST_SECOND_REDIS_URL_ENV} is not configured")

    async def scenario():
        async with resource_services(limits_services) as (_, first):
            second = Redis.from_url(disposable_redis_url(second_url))
            router = LiveShardRouter((limits_services[1], second_url))
            clients = (first, second)
            assert (await first.info("server"))["run_id"] != (
                await second.info("server")
            )["run_id"]
            hub = LiveSubscriptionHub(router, clients, first)
            store = FeedHealthStore(router, clients)
            ids = []
            for index in range(2):
                run_id = uuid4()
                while router.shard_for(run_id).index != index:
                    run_id = uuid4()
                ids.append(run_id)
            await hub.start()
            try:
                viewers = [await hub.attach(run_id) for run_id in ids]
                for index, run_id in enumerate(ids):
                    clock = hub._clocks[index]
                    sample = await clock.sample(clients[index])
                    permit = LivePermit(
                        run_id,
                        1,
                        index,
                        monotonic() + LIVE_PERMIT_SECONDS,
                        sample.deadline(LIVE_PERMIT_SECONDS),
                        clock.epoch,
                    )
                    assert await store.record(
                        permit,
                        FeedObservation.from_observation(
                            StreamHealth(0, 0, 0),
                            observed_at=system_now_utc() - timedelta(seconds=1),
                        ),
                        1,
                        clock,
                    )
                    assert await store.read(run_id) is not None
                    assert await clients[1 - index].get(store.key(run_id)) is None
                    assert (await clients[index].pubsub_numsub(router.channel(run_id)))[
                        0
                    ][1] == 1
                    assert (
                        await clients[1 - index].pubsub_numsub(router.channel(run_id))
                    )[0][1] == 0
                    await clients[index].publish(
                        router.channel(run_id),
                        PublishedSnapshot(
                            snapshot=snapshot(run_id),
                            publication_deadline_us=permit.redis_deadline_us,
                        ).model_dump_json(),
                    )
                await eventually(
                    lambda: all(viewer._live is not None for viewer in viewers)
                )
                unaffected = viewers[1]._live
                other_epoch = hub._clocks[1].epoch
                await first.client_kill_filter(_type="pubsub")
                await eventually(lambda: hub._clocks[0].epoch > 0)
                assert viewers[0]._live is None
                assert viewers[1]._live is unaffected and unaffected.fresh()
                assert hub._clocks[1].epoch == other_epoch
            finally:
                await hub.close()
                await second.aclose()

    asyncio.run(scenario())
