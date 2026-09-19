"""Explicit test doubles for lifecycle tests; real transport coverage lives separately."""

from uuid import uuid4

from api.events.contracts import LiveRunSnapshot
from api.events.contracts.payloads.lifecycle import FeedObservation
from api.events.health.contracts import FeedHealthRecord
from api.events.health.policy import FEED_TTL_SECONDS
from api.events.health.store import FeedHealthStore
from api.events.live.routing import LiveShardRouter


class RecordingLive:
    def __init__(self):
        self.snapshots = []
        self.observations = []
        self.closed = False
        self.interested = True

    def watched(self):
        return self.interested and not self.closed

    def publish(self, sample, *, occurred_at, health):
        self.snapshots.append(
            LiveRunSnapshot.from_sample(
                uuid4(),
                sample,
                occurred_at=occurred_at,
                generation=1,
                sequence=len(self.snapshots) + 1,
                health=health,
            )
        )

    def record_health(self, observation):
        self.observations.append(observation)
        return True

    def close(self):
        self.closed = True


class RecordingWorkerLive:
    def __init__(self):
        self.handles = []

    async def start(self):
        pass

    async def close(self):
        for handle in self.handles:
            handle.close()

    def for_execution(self, run_id, execution_token):
        handle = RecordingLive()
        self.handles.append(handle)
        return handle


def health_reader(redis):
    return FeedHealthStore(LiveShardRouter(("redis://fixture",)), (redis,))


async def seed_health(redis, run_id, health, *, observed_at):
    """Seed only read-adapter/monitor fixtures; this is not a publication path."""
    record = FeedHealthRecord(
        generation=1,
        sequence=1,
        observed_at_us=round(observed_at.timestamp() * 1_000_000),
        observation=FeedObservation.from_observation(health, observed_at=observed_at),
    )
    await redis.set(
        FeedHealthStore.key(run_id), record.model_dump_json(), ex=FEED_TTL_SECONDS
    )
