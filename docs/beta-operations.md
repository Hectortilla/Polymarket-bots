# Private beta operations

The current alert owner is **deployment operator (public contact pending)**. A named support/on-call identity is a
release prerequisite; the current label is explicitly a placeholder. No public
operator API, self-registration privilege, external alert service, or provider
purchase is configured. Host OS and Docker access grant maintenance authority.
Keep that access separate from ordinary service accounts; do not expose the
Docker socket, database credentials, or maintenance shell through the web app.
The audit actor is the invoking OS account. Use distinct OS accounts for operators;
shared container UIDs do not establish individual attribution.

Run commands from the repository root with the private runtime environment:

```sh
uv run --env-file .env python -m api.operations status
uv run --env-file .env python -m api.operations list-runs
uv run --env-file .env python -m api.operations inspect-run RUN_UUID
uv run --env-file .env python -m api.operations stop-run RUN_UUID
uv run --env-file .env python -m api.operations suspend ACCOUNT_UUID
uv run --env-file .env python -m api.operations resume-account ACCOUNT_UUID
uv run --env-file .env python -m api.operations stop-all
uv run --env-file .env python -m api.operations resume-admissions
```

Use actual UUIDs in place of the labels. `inspect-run` returns the owning account
UUID, lifecycle state, timestamps and event count without graph/config/payloads.
`list-runs` returns the same minimal inspection for unfinished runs, so an alert
can be diagnosed without a user-provided run ID. `status` exits nonzero when any
probe or operational condition is unhealthy; a missing control singleton is an
explicit failure. The journal records actor, target, action, outcome and timestamp atomically with
successful or unchanged mutations. Missing targets are journaled too. Dependency
failures exit nonzero without claiming success; transaction rollback preserves
previous state, and retry is safe even when a response was lost after commit.

Suspension revokes all sessions and recovery links. A concurrent login either
commits before suspension and is revoked or observes suspension and fails. Launch
and claim share the incident/admission lock. A suspension or stop-all transaction
stops queued rows, interrupts owned rows and writes lifecycle events; further
lease-protected fills and publications fail immediately after commit. Local worker
cleanup uses the configured heartbeat interval plus the cleanup budget, subject to
process scheduling; unresponsive processes may need the deployment's bounded
worker restart. Database unavailability cannot grant fresh execution. Resuming
never restarts a terminated run or restores a revoked session.

Default worker cleanup budget: heartbeat 5 seconds plus cleanup 10 seconds.
`POLYBOT_HEARTBEAT_SECONDS` changes the heartbeat portion.

## Measurements and alerts

Follow `docker compose --env-file MANIFEST -f deploy/compose.yaml logs -f recovery`.
Recovery emits JSON observations and alerts every five seconds plus probe time.
Every alert includes its code, threshold, operator owner and response instruction.
The table shows default thresholds. `stuck_run` uses the deployed
`POLYBOT_LEASE_SECONDS` value; its emitted threshold reflects that override.
Logs rotate at 10 MiB with 3 files per service. Typed operational records contain only aggregates, fixed codes and bounded status values; a bounded queue moves sink I/O off the event loop and reports dropped records when the sink recovers. No request URL, body, headers,
email, password, token, SDK payload or exception details are included. Existing
secret-safe dependency messages remain. Uvicorn access logging is disabled.

<!-- operational-alerts:start -->
| Alert | Condition | Threshold | Unit / interpretation | Response |
| --- | --- | ---: | --- | --- |
| `database_unavailable` | unavailable | 0 | successful probes | Check private PostgreSQL health and disk; do not resume admissions until reads succeed. |
| `control_unavailable` | unavailable | 0 | required control rows | Keep admission closed; repair the required control singleton using a reviewed forward migration. |
| `redis_unavailable` | unavailable | 0 | successful probes | Restore private Redis; queued rows remain durable. Check recovery delivery afterward. |
| `telemetry_invalid` | unavailable | 0 | valid telemetry probes | Inspect private telemetry records and worker configuration; malformed presence or counters cannot prove health. |
| `storage_unavailable` | unavailable | 0 | successful probes | Check the read-only storage probe mount; disk capacity is unknown. |
| `worker_unavailable` | unavailable | 30 | process presence TTL seconds; no valid presence | Check worker process logs and restart the matching release; old runs require explicit relaunch. |
| `queue_delay` | at_least | 120 | seconds | Inspect worker presence and queue age; stop admission if progress cannot recover. |
| `queue_capacity` | at_least | 8 | queued runs | Inspect allowances and worker throughput before reopening admissions. |
| `stuck_run` | unavailable | 30 | configured lease seconds; also missing heartbeat | Check recovery process; stop affected run or stop-all and verify terminal history. |
| `storage_growth` | at_least | 1.07374e+10 | bytes | Inspect database growth and lifecycle cleanup; stop admission before storage exhaustion. |
| `storage_low` | at_most | 5.36871e+09 | free bytes | Stop admission; restore storage headroom without deleting retained database rows manually. |
| `feed_unavailable` | unavailable | 45 | seconds since observation; also missing or invalid input | Inspect worker/feed observations; use stop-run if input remains unavailable. |
| `feed_degraded` | at_least | 5000 | dispatch lag ms; also stale book | Inspect stale-book and dispatch-lag signals; stop affected runs until input recovers. |
| `api_errors` | at_least | 5 | responses in current plus previous minute | Inspect API and dependency health; use incident stop for sustained failures. |
| `admission_rejections` | at_least | 10 | responses in current plus previous minute | Check account/global allowances and queue capacity; do not bypass configured limits. |
<!-- operational-alerts:end -->

Thresholds are owned by `api.operations.alerts`; counter/TTL policies by
the focused `api.operations.telemetry` adapters and `api.events.health.policy`. HTTP counts represent responses, not distinct users. Incident, suspension and capacity rejections are counted separately from server failures.
Feed alerts reuse existing worker observations; no Polymarket integration changes.
The read-only PostgreSQL-volume mount supplies actual deployment disk capacity.
Local `status` checks the current filesystem. Monitor the recovery process itself
with host process supervision: absent monitor logs are not proof of health.

For PostgreSQL outages, keep admission closed, check storage and restore database
availability. Existing lease fences reject progress; never manually reset run
statuses. For Redis outages, keep PostgreSQL intact: queued deliveries retry when
Redis returns. For worker/feed failures, inspect the affected run and stop it; a
fresh run requires an explicit user action. For failed deployment, follow
[release and rollback](beta-deployment.md); preserve ingress closure and never
assume schema downgrade is safe. Resume admissions only after status probes,
worker presence and queue progress recover. Test with a disposable account/run
before allowing new work. Resumption is an explicit operator command.

<!-- operational-cadence:start -->
| Policy | Value |
| --- | ---: |
| Monitor interval seconds | 5 |
| Process heartbeat seconds | 5 |
| Process presence TTL seconds | 30 |
| Feed observation TTL seconds | 45 |
| Counter window seconds (current plus previous) | 60 |
| Counter TTL seconds | 180 |
| Maximum queued log records | 1024 |
<!-- operational-cadence:end -->

The final public-opening checklist and contact prerequisites are in
[beta launch](beta-launch.md); completing these procedures does not itself open signup.
