"""Run the real live path on disposable local services; never certifies by declaration.

PYTHONPATH=backend/tests uv run python -m control_plane.live_telemetry_capacity --help
The dedicated Redis instances must be disposable: fault injection kills Pub/Sub
connections and flushes their script caches (these operations are server-wide).
"""

import argparse
import asyncio
import json
import multiprocessing
import os
import platform
import socket
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from alembic import command
from alembic.config import Config
from api.auth.store import AuthStore
from api.deployment.settings import StartupSettings
from api.execution.worker.database import create_worker_database
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from polybot.framework.clock import system_now_utc
from redis.asyncio import Redis
from sqlalchemy import func, select

from control_plane.disposable_services import (
    disposable_postgres_url,
    disposable_redis_url,
)
from control_plane.limits_fixtures import account_bot
from control_plane.live_capacity.checks import evaluate
from control_plane.live_capacity.measurements import Measurements
from control_plane.live_capacity.producer import run_producer
from control_plane.live_capacity.server import run_server
from control_plane.live_capacity.viewers import stalled_viewer, watch
from control_plane.service_config import TEST_POSTGRES_URL_ENV, TEST_REDIS_URL_ENV

PRODUCER_COUNTS = (1_000, 10_000, 20_000, 50_000)
WATCHED_PERCENTAGES = (0, 10, 100)
VIEWERS_PER_WATCHED_RUN = (1, 3)
TOKEN_COUNTS = (1, 10, 20)
MINIMUM_GATE_MINUTES = 30


@dataclass(frozen=True)
class LiveCapacityWorkload:
    producers: int
    watched_percent: int
    viewers_per_watched_run: int
    tokens: int
    duration_seconds: float
    worker_processes: int
    api_processes: int
    mode: str
    smoke: bool
    faults: bool
    slow_viewers: int
    hot_run_viewers: int
    bursts: bool

    def validate(self):
        if (
            min(
                self.producers,
                self.worker_processes,
                self.api_processes,
                self.duration_seconds,
            )
            <= 0
        ):
            raise ValueError("workload sizes and duration must be positive")
        if (
            self.watched_percent not in WATCHED_PERCENTAGES
            or self.tokens not in TOKEN_COUNTS
            or self.viewers_per_watched_run not in VIEWERS_PER_WATCHED_RUN
        ):
            raise ValueError("unsupported matrix cell")
        if not self.smoke and (
            self.producers not in PRODUCER_COUNTS
            or self.duration_seconds < MINIMUM_GATE_MINUTES * 60
        ):
            raise ValueError(
                "capacity gates require a matrix producer count and at least 30 minutes; use --smoke for development"
            )
        if min(self.slow_viewers, self.hot_run_viewers) < 0:
            raise ValueError("slow viewers must be nonnegative")
        if self.worker_processes > self.producers:
            raise ValueError("each worker process must have at least one producer")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producers", type=int, required=True)
    parser.add_argument(
        "--watched-percent", type=int, choices=WATCHED_PERCENTAGES, required=True
    )
    parser.add_argument(
        "--viewers", type=int, choices=VIEWERS_PER_WATCHED_RUN, required=True
    )
    parser.add_argument("--tokens", type=int, choices=TOKEN_COUNTS, required=True)
    parser.add_argument("--duration-seconds", type=float, default=1800)
    parser.add_argument("--worker-processes", type=int, required=True)
    parser.add_argument("--api-processes", type=int, required=True)
    parser.add_argument("--mode", choices=("isolated", "integrated"), required=True)
    parser.add_argument(
        "--live-redis-url",
        action="append",
        help="ordered dedicated disposable shard URL; repeat per shard",
    )
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--faults", action="store_true")
    parser.add_argument("--slow-viewers", type=int, default=0)
    parser.add_argument("--hot-run-viewers", type=int, default=0)
    parser.add_argument("--bursts", action="store_true")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    workload = LiveCapacityWorkload(
        args.producers,
        args.watched_percent,
        args.viewers,
        args.tokens,
        args.duration_seconds,
        args.worker_processes,
        args.api_processes,
        args.mode,
        args.smoke,
        args.faults,
        args.slow_viewers,
        args.hot_run_viewers,
        args.bursts,
    )
    workload.validate()
    postgres = disposable_postgres_url(
        os.environ[TEST_POSTGRES_URL_ENV]
    ).render_as_string(hide_password=False)
    redis = disposable_redis_url(os.environ[TEST_REDIS_URL_ENV])
    shards = tuple(
        disposable_redis_url(value) for value in args.live_redis_url or [redis]
    )
    if len({(urlsplit(url).hostname, urlsplit(url).port) for url in shards}) != len(
        shards
    ):
        raise ValueError(
            "shards must be distinct Redis servers, not databases on one server"
        )
    settings = StartupSettings(
        database_url=postgres, redis_url=redis, live_redis_urls=shards
    )
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres)
    command.upgrade(config, "head")
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(rehearse(settings, workload, args.manifest))


async def rehearse(settings, workload, manifest):
    context = multiprocessing.get_context("spawn")
    engine, sessions = create_worker_database(settings.database_url.get_secret_value())
    user, bot = await account_bot(sessions)
    rows = []
    async with sessions() as session:
        cookie = (await AuthStore(session).issue_session(user, None)).value
        for _ in range(workload.producers):
            row = RunRow(
                bot_id=bot.id,
                definition_id=bot.definition_id,
                config_snapshot=bot.config.model_dump(mode="json"),
                status=RunStatus.RUNNING,
                started_at=system_now_utc(),
                heartbeat_at=system_now_utc(),
                execution_token=uuid4(),
            )
            session.add(row)
            rows.append((str(row.id), str(row.execution_token)))
        await session.commit()
    # Direct row seeding is explicit test-only admission. No production quotas change.
    clients = [
        Redis.from_url(value.get_secret_value()) for value in settings.live_redis_urls
    ]
    measurements = Measurements()
    captured = deque(maxlen=256)
    capture_before_stop = []
    processes, sockets, viewers, faults = [], [], [], []
    directory = manifest.parent / (manifest.stem + "-processes")
    directory.mkdir(exist_ok=True)
    viewer_stop = asyncio.Event()
    http = httpx.AsyncClient(
        timeout=httpx.Timeout(10, read=None),
        trust_env=False,
        limits=httpx.Limits(
            max_connections=workload.producers * workload.viewers_per_watched_run
            + workload.hot_run_viewers
            + 1
        ),
    )

    def spawn(role, index, generation=0, sock=None):
        stop = context.Event()
        report = directory / f"{role}-{index}-{generation}.json"
        if role == "worker":
            args = (
                settings,
                rows[index :: workload.worker_processes],
                workload.tokens,
                workload.mode,
                stop,
                report,
                workload.bursts,
            )
            target = run_producer
        else:
            args = (settings, sock, stop, report, workload.duration_seconds)
            target = run_server
        process = context.Process(
            target=target, args=args, name=f"live-capacity-{role}-{index}"
        )
        process.start()
        entry = dict(
            process=process,
            stop=stop,
            report=report,
            role=role,
            index=index,
            generation=generation,
            sock=sock,
        )
        processes.append(entry)
        return entry

    origins = []
    started = monotonic()
    failure = None
    try:
        for index in range(workload.api_processes):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            sock.setblocking(False)
            sockets.append(sock)
            origins.append(f"http://127.0.0.1:{sock.getsockname()[1]}")
            spawn("api", index, sock=sock)
        for index in range(workload.worker_processes):
            spawn("worker", index)
        watched = rows[: round(len(rows) * workload.watched_percent / 100)]
        for index, (run_id, _) in enumerate(watched):
            for viewer in range(workload.viewers_per_watched_run):
                origin = origins[(index + viewer) % len(origins)]
                viewers.append(
                    asyncio.create_task(
                        watch(
                            http,
                            origin,
                            run_id,
                            cookie,
                            viewer_stop,
                            measurements,
                            captured,
                        )
                    )
                )
        for index in range(workload.hot_run_viewers):
            viewers.append(
                asyncio.create_task(
                    watch(
                        http,
                        origins[index % len(origins)],
                        rows[0][0],
                        cookie,
                        viewer_stop,
                        measurements,
                        captured,
                    )
                )
            )
        for index in range(workload.slow_viewers):
            if watched:
                viewers.append(
                    asyncio.create_task(
                        stalled_viewer(
                            origins[index % len(origins)],
                            watched[index % len(watched)][0],
                            cookie,
                            viewer_stop,
                        )
                    )
                )
        fault_step = 0
        next_report = 0
        while monotonic() - started < workload.duration_seconds:
            elapsed = monotonic() - started
            if any(entry["process"].exitcode not in (None, 0) for entry in processes):
                raise RuntimeError("capacity child failed; inspect its process report")
            for viewer in viewers:
                if viewer.done() and viewer.exception() is not None:
                    raise viewer.exception()
            if (
                workload.faults
                and elapsed >= workload.duration_seconds * (fault_step + 1) / 5
                and fault_step < 4
            ):
                if fault_step == 0:
                    for redis in clients:
                        await redis.script_flush()
                    name = "script-cache-flush"
                elif fault_step == 1:
                    for redis in clients:
                        await redis.client_kill_filter(_type="pubsub")
                    name = "pubsub-disconnect"
                else:
                    role = "worker" if fault_step == 2 else "api"
                    old = next(
                        entry
                        for entry in reversed(processes)
                        if entry["role"] == role and entry["index"] == 0
                    )
                    old["stop"].set()
                    await asyncio.to_thread(old["process"].join, 10)
                    if old["process"].is_alive():
                        raise TimeoutError("process failed to drain for restart")
                    spawn(role, 0, old["generation"] + 1, old["sock"])
                    name = role + "-restart"
                faults.append(dict(action=name, elapsed_seconds=elapsed))
                fault_step += 1
            if elapsed >= next_report:
                for index, redis in enumerate(clients):
                    info = await redis.info()
                    measurements.observe(
                        f"redis_{index}_rss_bytes", info["used_memory_rss"]
                    )
                    measurements.observe(
                        f"redis_{index}_clients", info["connected_clients"]
                    )
                    measurements.observe(
                        f"redis_{index}_ops_per_second",
                        info["instantaneous_ops_per_sec"],
                    )
                await measurements.write(
                    manifest, {}, status="running", workload=asdict(workload)
                )
                next_report = elapsed + 2
            await asyncio.sleep(0.1)
        if workload.mode == "integrated":
            capture_before_stop = list(captured)[-128:]
            async with asyncio.timeout(30):
                for run_id, _ in rows:
                    async with sessions() as session:
                        await RunStore(session).request_stop(
                            UUID(run_id), now=system_now_utc()
                        )
                expected_viewers = (
                    len(watched) * workload.viewers_per_watched_run
                    + workload.hot_run_viewers
                )
                while True:
                    async with sessions() as session:
                        stopped = await session.scalar(
                            select(func.count())
                            .select_from(RunRow)
                            .where(
                                RunRow.bot_id == bot.id,
                                RunRow.status == RunStatus.STOPPED,
                            )
                        )
                    if (
                        stopped == workload.producers
                        and measurements.counts.get("viewers_with_terminal", 0)
                        == expected_viewers
                    ):
                        break
                    await asyncio.sleep(0.1)
    except Exception as error:
        failure = error
    finally:
        viewer_stop.set()
        for task in viewers:
            task.cancel()
        await asyncio.gather(*viewers, return_exceptions=True)
        for entry in processes:
            entry["stop"].set()
        for entry in processes:
            await asyncio.to_thread(entry["process"].join, 10)
            if entry["process"].is_alive():
                entry["process"].terminate()
                await asyncio.to_thread(entry["process"].join, 5)
        await http.aclose()
        for sock in sockets:
            sock.close()
        for client in clients:
            await client.aclose()
        # Keep owned rows/history for inspection in the dedicated test database.
        await engine.dispose()
    reports = [
        {
            **json.loads(entry["report"].read_text()),
            "role": entry["role"],
            "index": entry["index"],
        }
        for entry in processes
        if entry["report"].exists()
    ]
    capture_path = manifest.with_suffix(".frames.json")
    replay_frames = (
        capture_before_stop + list(captured)[-128:]
        if capture_before_stop
        else list(captured)
    )
    capture_path.write_text(json.dumps(replay_frames) + "\n")
    browser_replay = None
    if captured:
        log_path = manifest.with_suffix(".browser.log")
        with log_path.open("w") as log:
            process = await asyncio.create_subprocess_exec(
                "npm",
                "--prefix",
                "frontend",
                "test",
                "--",
                "src/lib/charts/capacityReplay.test.ts",
                env={**os.environ, "POLYBOT_LIVE_CAPTURE": str(capture_path.resolve())},
                stdout=log,
                stderr=log,
            )
            browser_replay = await process.wait()
    exit_codes = [entry["process"].exitcode for entry in processes]
    checks, passed = evaluate(
        measurements, reports, workload, exit_codes, browser_replay
    )
    checks["runner_completed"] = failure is None
    passed = passed and failure is None
    await measurements.write(
        manifest,
        {},
        checks=checks,
        measured_checks_passed=passed,
        browser_replay_exit_code=browser_replay,
        status="measured-not-certified" if passed else "failed",
        workload=asdict(workload),
        recorded_at=datetime.now(UTC).isoformat(),
        host=platform.platform(),
        cpu_count=os.cpu_count(),
        shard_count=len(clients),
        process_reports=reports,
        faults=faults,
        child_exit_codes=exit_codes,
        failure_type=None if failure is None else type(failure).__name__,
        browser_fixture=str(capture_path),
        production_admission_unchanged=True,
        execution_monitoring=(
            "production_owned_heartbeat_and_stop"
            if workload.mode == "integrated"
            else "synthetic_batched_heartbeat"
        ),
        restart_semantics="synthetic producer restarts retain test execution tokens; not production bot recovery",
        admission_overrides={
            "request_count": "disabled",
            "stream_count": "disabled",
            "stream_lease_seconds": workload.duration_seconds + 60,
        },
        sample_window="last 4096 observations per metric",
        unverified=[
            "20k/50k gates unless independently run",
            "four-hour soak",
            "deployment proxy",
            "browser rendering at target scale",
            "per-node CPU/network headroom",
            "stable memory over soak",
        ],
    )
    if not passed:
        raise RuntimeError(
            "measured capacity checks failed; inspect manifest.checks"
        ) from failure


if __name__ == "__main__":
    main()
