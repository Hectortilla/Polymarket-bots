"""HTTP SSE receivers with bounded capture for the real frontend merge fixture."""

import asyncio
import json
from time import monotonic, time

import httpx
from api.auth.policy import SESSION_COOKIE
from api.events.kinds import EventKind, LiveEventKind
from api.events.live.policy import LIVE_MAX_SNAPSHOT_BYTES
from api.http.routes.paths import RUN_EVENTS_STREAM_PATH, api_route_path
from api.runs.status import TERMINAL_RUN_STATUSES


async def watch(client, origin, run_id, cookie, stop, measurements, capture):
    last_id = 0
    identity = (0, 0)
    received_live = False
    while not stop.is_set():
        try:
            async with client.stream(
                "GET",
                origin + api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run_id),
                cookies={SESSION_COOKIE: cookie},
                headers={"Last-Event-ID": str(last_id)},
            ) as response:
                response.raise_for_status()
                measurements.add("http_connections")
                connected_at = monotonic()
                initial = True
                async for line in response.aiter_lines():
                    if stop.is_set():
                        return
                    if len(line) > LIVE_MAX_SNAPSHOT_BYTES * 2:
                        raise ValueError("unbounded SSE line")
                    if line.startswith("id:"):
                        event_id = int(line[3:].strip())
                        if event_id <= last_id:
                            measurements.add("cursor_regressions")
                        last_id = event_id
                    if not line.startswith("data:"):
                        continue
                    payload = json.loads(line[5:])
                    capture.append(payload)
                    if payload.get("kind") == LiveEventKind.RUN_SNAPSHOT:
                        if not received_live:
                            received_live = True
                            measurements.add("viewers_with_live")
                        if initial:
                            measurements.observe(
                                "initial_live_seconds", monotonic() - connected_at
                            )
                            initial = False
                        current = payload["generation"], payload["sequence"]
                        if current <= identity:
                            measurements.add("identity_regressions")
                        identity = current
                        measurements.add("live_frames")
                        measurements.observe(
                            "snapshot_age_seconds",
                            max(0, time() - payload["sampled_at_ms"] / 1000),
                        )
                    else:
                        measurements.add("durable_frames")
                        if (
                            payload.get("kind") == EventKind.RUN_LIFECYCLE
                            and payload["payload"]["status"] in TERMINAL_RUN_STATUSES
                        ):
                            measurements.add("viewers_with_terminal")
                            return
        except (httpx.HTTPError, OSError):
            measurements.add("http_reconnects")
            await asyncio.sleep(0.2)


async def stalled_viewer(origin, run_id, cookie, stop):
    """Do not drain the TCP socket: exercise server/kernel/proxy backpressure."""
    port = int(origin.rsplit(":", 1)[1])
    while not stop.is_set():
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", port, limit=1024
            )
            break
        except OSError:
            await asyncio.sleep(0.2)
    else:
        return
    path = api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run_id)
    writer.write(
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nCookie: {SESSION_COOKIE}={cookie}\r\n\r\n".encode()
    )
    await writer.drain()
    try:
        while not stop.is_set():
            await asyncio.sleep(0.2)
    finally:
        writer.close()
        await writer.wait_closed()
