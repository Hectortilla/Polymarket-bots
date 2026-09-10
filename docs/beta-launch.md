# Public paper-beta release gate

Slices 16–23 supply the implementation and repeatable acceptance. Completion does
not expose the deployment or invite public accounts. Keep the private ingress
boundary until the operator completes and records every gate below.

## Ownership and contact readiness

The application service name remains a working name. The deployment operator,
incident/on-call owner, privacy contact and support mailbox are **placeholders**,
as approved for this implementation. `api.service_identity` owns the service name
used by SMTP and exports it to the generated browser contract; the dependency-light
`frontend/src/lib/serviceIdentity.ts` supplies browser titles and branding.
`frontend/src/lib/public/identity.ts` owns the public operator/contact. Its support page explicitly says contact is not
configured and accepts no messages. Before opening, replace the placeholders
with the actual responsible identity and monitored mailbox, review the service
terms/privacy notice, test mailbox receipt and recovery/verification delivery,
and record who covers incidents and backup recovery. Do not advertise a response
SLA until one is staffed.

## Anonymous surface

The exact information-page allowlist is owned by
`frontend/src/lib/public/navigation.ts`: overview, help, privacy, terms and support.
These static pages require no account lookup, usage request or private resource
preload. Account-entry/recovery pages retain their separate allowlist. Navigating
to a private page restores the session before rendering its keyed account view.
The HTTP allowlist remains the method/path pairs in `api.auth.policy.PUBLIC_ROUTES`:
health and the existing authentication/recovery operations. No new anonymous API
or operator endpoint is introduced. The bot dashboard remains private.

## Acceptance and evidence

Run from the repository root with README's real disposable PostgreSQL/Redis
settings. All service-dependent tests must run; a green result with skipped
service checks is not release evidence. Use a separate database/Redis index for
browser acceptance and do not run overlapping suites against the same database.

```sh
uv run pytest
npm --prefix frontend run generate:check
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
uv build
PYTHONPATH=backend/tests uv run python -m control_plane.limits_load
PYTHONPATH=backend/tests uv run python -m control_plane.deployment_smoke
PYTHONPATH=backend/tests uv run python -m control_plane.backup_rehearsal
```

The backend suite covers signup/verification/recovery, ownership, launch admission
and concurrency, Stop/lease failure recovery, private operator actions and alerts,
retention and deletion. Browser scenarios cover account switching and revoked
streams, recovery links, uncertain launch recovery, deletion, and guided action
and no-action paper runs. Anonymous navigation asserts no API requests. The HTTPS
rehearsal runs the built UI through guided setup, verification, login, launch,
Stop and reload, then exercises queueing, worker/dependency loss, operator controls,
release/rollback and failed migrations. Its market fixture does not assume a trade.
The encrypted restore rehearsal verifies ownership/history and paused quarantine
before access, including authenticated invalid-dump refusal.

Acceptance results and final reviewer disposition are recorded in this slice's
implementation-plan entry. Temporary local logs and protected disposable artifacts
are under `data/` or the named `/tmp/polybot-s23-*` logs; do not publish credentials,
recovery mail, database archives or private fixture manifests with a release report.

## Capacity and known limits

`api.limits.policy.PAPER_BETA` owns active/queued run, duration, graph/storage,
market/wallet, request and stream allowances. Generated browser contracts supply
public help and signed-in usage; do not duplicate configurable allowances in
release configuration. The bounded load rehearsal measures local synthetic book
handling, durable writes/reads and stream delivery with configured global capacity.
It is not a measurement of Polymarket capacity, Internet latency or a deployment
host's sustained throughput. Rerun on the target host before increasing allowances.

Paper fills, latency, fees and equity are simulations. Market inputs may be stale,
missing or unavailable; legitimate conditions can produce no orders. History is
bounded; loaded events can cover only a portion of a run. Private draft saving
blocks uncertain resends in the current editor but does not persist a resumable
save operation across reloads. Live execution, billing, marketplaces, browser
backtesting and performance guarantees are outside this beta.

## Recorded local acceptance

The 2026-09-10 release-candidate checks passed 1,389 backend tests (real disposable
services, no service skips), 314 frontend tests and 11 browser scenarios. Generated
parity, zero-diagnostic Svelte checks and frontend/Python builds passed. HTTPS
release/fault/rollback and encrypted restore rehearsals passed; isolated restore
took 7.2 seconds and started no prior jobs.

| Synthetic load measure | Recorded result |
| --- | --- |
| Observation window | 15 seconds |
| Books / durable writes / reads | 22,160 / 221 / 247 |
| Stream frames / budgeted requests | 1,768 / 247 |
| p95 I/O / event-loop lag | 154.83 ms / 5.84 ms |

These are bounded local fixture results. Repeat the checklist on the deployment
host and retain reviewed release evidence before opening or changing allowances.
The operator/support identity and real deployment setup gates are still pending.

## Final opening checklist

- Record the release commit/images, host, time and named accountable operator.
- Obtain passing complete tests, generated parity, builds, browser, load, HTTPS
  failure/rollback and encrypted restore evidence for the release under review.
- Replace the operator/support placeholders, review visible privacy/terms and
  test support plus account email delivery. Verify recovery and deletion paths.
- Install and supervise the recovery/monitor processes; route structured alerts
  to the named incident owner and rehearse acknowledgement. See
  [operations](beta-operations.md).
- Install daily encrypted off-host backups, custody recovery keys separately,
  enforce the approved retention and check the backup-age alarm. Reconcile
  deletion receipts on restore before removing quarantine. See
  [data lifecycle](beta-data-lifecycle.md).
- Confirm target-host capacity and storage headroom at configured limits. Verify
  database/Redis remain private, secure cookies/TLS/origin settings are correct,
  credentials are unique, and rollback images are schema compatible. See
  [deployment](beta-deployment.md).
- Audit README, product spec, both architecture documents, implementation plan,
  operator runbooks and generated contracts for drift.
- Only then deliberately configure the approved public ingress/domain and invite
  users. Record the action separately from the coding commit. Keep a tested route
  to incident pause and rollback; never restore and reopen automatically.
