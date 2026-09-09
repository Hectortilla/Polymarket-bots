# Private staging and release operations

Slice 16 adopts the architecture's single-host Docker Compose topology. It adds
no hosting account, paid provider, public binding, or production deployment.
The staging baseline is Linux/arm64 or Linux/amd64 with Docker Compose v2,
four CPU cores, 8 GiB RAM and 40 GiB free disk. These are rehearsal assumptions,
not a measured public capacity promise. Slice 17's `api.limits.policy.PAPER_BETA`
owns the initial limits; its bounded synthetic rehearsal is recorded in the
implementation plan and must be repeated on the target host.

`deploy/compose.yaml` contains the static Caddy frontend, two-process API,
Taskiq worker, PostgreSQL, Redis and a one-shot forward migration. Only Caddy
publishes a port, always on loopback. PostgreSQL and Redis use an internal network;
API and worker have outbound access for market discovery/data. The dedicated
proxy subnet must not overlap host routes. Uvicorn trusts only Caddy's fixed
address; Caddy replaces forwarded address/scheme/host headers and removes
`Forwarded`. SSE is flushed immediately. HTTPS uses externally supplied certificate
files; certificate acquisition and a real hostname remain operator inputs.
Caddy's readiness probe binds only to loopback inside its container; that HTTP
listener is not published. Release activation waits for both API readiness and
the configured proxy to become healthy. The TLS/browser rehearsal separately
verifies the supplied certificate and authenticated request path.
See [Caddy proxy behavior](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
and [Compose migration ordering](https://docs.docker.com/compose/how-tos/startup-order/).

The entrypoint remains private until every Slice 16–23 acceptance gate passes.
Opening signup requires a separate operational change. No command in this
repository publishes public ingress.

## Build and configuration

Build from the repository root with
`docker build -f deploy/backend.Dockerfile -t polybot-backend:BUILD .` and
`docker build -f deploy/frontend.Dockerfile -t polybot-frontend:BUILD .`.
Dependency lockfiles are installed without updates. Record the source
commit and resulting image IDs (`docker image inspect --format '{{.Id}}' TAG`)
in a copy of `deploy/release.env.example`. Production manifests accept only
image IDs or registry references containing SHA-256 digests, including the
PostgreSQL and Redis images. Tags are build conveniences, not release inputs.
Retain both previous and candidate manifests and images outside the source tree.
For deployable releases, build a clean commit; local rehearsals may exercise
uncommitted changes and must not be represented as release provenance.

Supply an absolute runtime secret directory, kept outside the build context,
containing `database_url`, `redis_url`, `postgres_password`, `tls_cert`, and
`tls_key`. Use a host directory accessible only to the operator. Secret files
must be readable by the receiving container user (backend UID 10001); Compose
mounts only the declared individual secrets into each service. Backend URLs
use the private service names `postgres` and `redis`; the database name and
user are `polybot`. Redis is unauthenticated only inside its unexposed internal
network. The database password in its URL must match `postgres_password`.
Never pass credentials as build arguments or copy `.env` into an image.
Do not include TLS private keys or database/Redis credentials in release manifests.
See [Compose runtime secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

Set `POLYBOT_AUTH_ORIGIN` to the exact HTTPS browser origin and
`POLYBOT_HTTPS_PORT` to its port. For local TLS staging use
`https://localhost:8443` and trust the rehearsal certificate only in the test
client. Production rejects HTTP opt-in, mutable release IDs, missing secret
files, invalid proxy addresses and invalid numeric settings. Startup failure
reports configuration/dependency/schema failure without logging input values.

`StartupSettings` owns database/Redis configuration, worker concurrency,
heartbeat and lease settings. `PAPER_BETA.global_active_runs` owns the worker-concurrency default.
Intervals must be finite and positive, with lease greater than heartbeat.
API startup also validates settings when launched directly. Local development
continues to use README's Vite/Uvicorn commands and explicit HTTP opt-in.

## Release and rollback

Run `uv run python -m scripts.beta_release /absolute/path/release.env`.
The command validates immutable inputs, waits for infrastructure, closes the
entrypoint and stops application processes, runs the one-shot forward migration,
then starts `api`, `worker` and `recovery` and reopens private ingress only after API readiness.
The application requires the exact migration head shipped in its image. An
unsuccessful migration leaves ingress closed; diagnose and repair forward before
retrying. Existing test CI remains in place; deployment checks are additional.
Application releases preserve existing PostgreSQL/Redis containers rather than
upgrading infrastructure in place. Infrastructure version changes require their
own maintenance plan. Run releases serially for a given Compose project.

For rollback, select the previous retained manifest and pass `--rollback`.
This runs a compatibility check instead of Alembic downgrade. Rollback is
allowed only when the previous image supports the current schema (currently
exact-head compatibility). A schema-changing release needs a tested forward
repair or an explicitly compatible previous build; do not improvise a downgrade.
The check happens with ingress closed. A failed rollback remains closed.
Releases deliberately have a short outage and interrupt unfinished paper runs;
Slice 18 owns bounded automatic recovery of those interruptions.

Stop with `docker compose --env-file MANIFEST -f deploy/compose.yaml stop`.
Keep volumes and immutable images. Never use `down --volumes` against retained
data. Database/schema preservation applies to existing Slice 15 accounts too.

## Capacity and acceptance

The current durable dashboard cadence is at most one sample per active run per
second. Multiply `PAPER_BETA.global_active_runs` by the seconds in the observation
window to estimate chart rows, then add lifecycle, activity and order/fill events; measure payload and index bytes before expanding
capacity. No indefinite history promise is made. Slice 17 owns admission policy,
Slice 18 the recovery scheduler, Slice 20 alerts and Slice 21 retention/backups.

The deployment rehearsal uses isolated containers/volumes and a generated local
TLS certificate. Its market/runtime fixture is confined to a separate test
image; production images contain no acceptance fixture. Identity, ownership,
database, Redis, Taskiq delivery, lifecycle and reverse proxy are real. It must
prove migration gating, shared multi-process reads, bounded worker concurrency,
queued/active Stop, durable progress/reload, SSE reconnect and scheduled lease
reconciliation after worker loss. Rehearse release and same-schema rollback,
then verify no service other than the loopback entrypoint publishes ports.
The reconnect check sends the last durable event ID and observes a later terminal
event without replaying the earlier event. Captured command/service logs are
checked for the test database password and browser session tokens before being
saved; application credentials never enter frontend builds or image build inputs.

Run it from the repository root with
`PYTHONPATH=backend/tests uv run python -m control_plane.deployment_smoke`.
Its uniquely named `polybot-beta-test-*` project and volumes are removed even on
failure; logs and generated inputs stay under git-ignored `data/beta/`. It
requires local port 8443 and the proxy subnet to be free. Never reuse this
destructive disposable harness for retained data. Deployment CI runs the same
command in addition to existing account and frontend jobs.
Install frontend dependencies and Chromium first with `npm --prefix frontend ci`
and `npm --prefix frontend exec -- playwright install chromium`.


Slice 18 adds the `recovery` service to release shutdown/startup. Local stacks must
also run `uv run --env-file .env python -m api.execution.recovery`. It retries queue
delivery and reconciles expired worker leases on the architecture policy cadence. Run history is
preserved and interrupted runs require a new launch. Migration 0006 is forward-only
in production and preserves accounts; older exact-head releases cannot roll back
across this schema change. During a database outage recovery waits for the database,
and Redis outages keep queue entries durable. See the architecture's Slice 18
section for lease, I/O and shutdown bounds. Open signup remains gated.
