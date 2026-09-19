"""Bounded workload measurements and secret-free process reports."""

import asyncio
import json
import os
import platform
import resource
from collections import deque
from contextvars import ContextVar
from pathlib import Path
from time import monotonic

from sqlalchemy import event

SQL_PHASE = ContextVar("capacity_sql_phase", default="other")


class Measurements:
    def __init__(self):
        self.started = monotonic()
        self.counts = {}
        self.samples = {}

    def instrument_live(self, publisher):
        for owner, method, phase in (
            (publisher._redis, "publish", "live_publish"),
            (publisher._health, "record", "health_write"),
        ):
            self.counts[phase + "_sql_queries"] = 0
            self.counts[phase + "_sql_checkouts"] = 0
            original = getattr(owner, method)

            async def measured(*args, _original=original, _phase=phase, **kwargs):
                token = SQL_PHASE.set(_phase)
                started = monotonic()
                try:
                    return await _original(*args, **kwargs)
                finally:
                    self.observe(_phase + "_seconds", monotonic() - started)
                    SQL_PHASE.reset(token)

            setattr(owner, method, measured)

    def add(self, name, amount=1):
        self.counts[name] = self.counts.get(name, 0) + amount

    def observe(self, name, value):
        self.samples.setdefault(name, deque(maxlen=4096)).append(value)

    def instrument_sql(self, engine):
        @event.listens_for(engine.sync_engine, "checkout")
        def checkout(connection, record, proxy):
            self.add(SQL_PHASE.get() + "_sql_checkouts")

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def before(conn, cursor, statement, parameters, context, many):
            context.capacity_started = monotonic()

        @event.listens_for(engine.sync_engine, "after_cursor_execute")
        def after(conn, cursor, statement, parameters, context, many):
            self.add("sql_queries")
            self.add(SQL_PHASE.get() + "_sql_queries")
            self.observe("sql_seconds", monotonic() - context.capacity_started)

    async def write(self, path: Path, telemetry, **extra):
        usage = resource.getrusage(resource.RUSAGE_SELF)
        distributions = {}
        for name, values in self.samples.items():
            ordered = sorted(values)
            distributions[name] = {
                f"p{percentile}": ordered[
                    min(len(ordered) - 1, int(len(ordered) * percentile / 100))
                ]
                for percentile in (50, 95, 99)
            }
            distributions[name]["retained_samples"] = len(ordered)
            distributions[name]["max"] = ordered[-1]
        result = dict(
            pid=os.getpid(),
            elapsed_seconds=monotonic() - self.started,
            cpu_seconds=usage.ru_utime + usage.ru_stime,
            max_rss_bytes=usage.ru_maxrss
            * (1 if platform.system() == "Darwin" else 1024),
            counts=dict(self.counts),
            recent_distributions=distributions,
            telemetry=telemetry,
            **extra,
        )
        await asyncio.to_thread(self._save, path, result)

    @staticmethod
    def _save(path, result):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(path)
