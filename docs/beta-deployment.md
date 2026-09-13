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
containing `database_url`, `redis_url`, `postgres_password`, `smtp_username`, `smtp_password`, `tls_cert`, and
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

## Laptop-to-server automation

Three commands automate the existing private release workflow. Run them from a
checkout of this repository on each machine, with Git, uv and Python 3.12+;
`uv sync --locked --no-dev` installs the command dependencies. The main laptop
needs Docker with Buildx and a builder capable of the target Linux architecture.
The Debian host needs Docker Engine and Compose v2 accessible to your normal
user. Its active Docker context must use a local Unix socket, with `DOCKER_HOST`
and `DOCKER_CONTEXT` unset. No image compilation runs on the Debian host.

Use a GitHub personal access token (classic) with `write:packages` for publishing,
and a separate token with `read:packages` and access to those packages for the
server. Organization packages may require SSO authorization. Both commands prompt
without echo; an already-exported `GITHUB_TOKEN` is also accepted and removed
from the subprocess environment before subsequent commands. Login uses
`--password-stdin`. Docker manages stored registry credentials through its
configured credential store. See [GitHub's GHCR authentication instructions](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

**1. Build and push on the main laptop.** Commit the changes being released first.
The command refuses a dirty worktree and builds a temporary `git archive` of the
commit, excluding ignored local files such as credentials and dependencies.

```sh
uv run python -m scripts.beta_publish \
  --namespace YOUR_GITHUB_USER_OR_ORG \
  --username YOUR_GITHUB_USER \
  --platform linux/amd64 \
  --output "$HOME/polybot-release-1.env"

scp "$HOME/polybot-release-1.env" SERVER_USER@SERVER_HOST:~/
```

Use a lowercase namespace. The default platform is `linux/amd64` for an Intel/AMD
Debian laptop, even when building on an Apple Silicon Mac. Use `linux/arm64` for
an ARM server. Images are pushed as `ghcr.io/NAMESPACE/polybot-backend:COMMIT`
and `ghcr.io/NAMESPACE/polybot-frontend:COMMIT`. The output records their registry
digests, the source commit, and the resolved PostgreSQL/Redis digests. Defaults
are the rehearsal's `postgres:17` and `redis:7-alpine`; `--postgres-image` and
`--redis-image` accept explicit references. The script never replaces an existing
output manifest. If a build fails after the other image was pushed, rerun with a
fresh output path; only a fully successful run produces a manifest.
Buildx supplies the pushed digest via its
[build metadata file](https://docs.docker.com/reference/cli/docker/buildx/build/#write-build-result-metadata-to-a-file---metadata-file).

**2. Prepare the Debian host once.** Clone/fetch this repository on the host so
the published source commit is available locally. Run from that checkout.
Provide a certificate valid for your chosen origin and its matching unencrypted private key,
plus your existing SMTP relay settings:

```sh
uv run python -m scripts.beta_setup \
  --release "$HOME/polybot-release-1.env" \
  --origin https://localhost:8443 \
  --tls-cert /absolute/path/cert.pem \
  --tls-key /absolute/path/key.pem \
  --smtp-host smtp.example.com \
  --smtp-from accounts@example.com
```

The script prompts for SMTP username/password, generates a random database
password and matching database URL, and prepares:

```text
~/app/                      mode 700
  .env                      mode 600; image/origin/SMTP settings, secret directory
  docker-compose.yml        exact deploy/compose.yaml from the release commit
  secrets/                  mode 700
    database_url, postgres_password, redis_url
    smtp_username, smtp_password, tls_cert, tls_key
```

Credentials stay in runtime secret files, following the existing Compose
contract. Individual secrets are mode `444` inside the private directory so
bind mounts are readable by backend UID 10001 without granting other host users
directory traversal. Keep both parent directories private. This uses
[Compose file secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
TLS inputs must be regular files, not symlinks. Setup captures their contents
and checks that the TLS key matches the certificate; hostname validity and
client trust remain part of the HTTPS rehearsal. Certificate acquisition and
renewal remain operator responsibilities. `--smtp-port 465 --smtp-security tls`
selects implicit TLS; defaults are port 587 and STARTTLS. Setup refuses a nonempty
destination and never rotates existing credentials. `--app-dir` selects another
directory outside the repository; use the same option on startup.

**3. Pull, migrate, start and watch logs on the Debian host.**

```sh
uv run python -m scripts.beta_start --username YOUR_GITHUB_USER
```

This logs in, pulls all pinned images before interrupting any services, and
calls the same `BetaRelease` sequence used by `scripts.beta_release`. It preserves
the PostgreSQL/Redis containers and volumes, closes ingress, stops applications,
runs the migration, starts applications and waits for readiness before reopening
private ingress. A failed migration leaves ingress closed. Logs follow with the
last 100 lines; Ctrl-C during log following leaves containers running. Use
`--no-logs` for a command that returns after activation. Re-running startup
performs another release cycle and interrupts paper runs.

The host stores each attempt's candidate and previous configuration under
`~/app/releases/`. On success it updates `~/app/.env` and `docker-compose.yml`.
A private `~/app/.deployment.json` journal records the candidate and rollback
mode before activation. If activation is interrupted, rerun the same startup
command without `--release`: it resumes that retained candidate and mode. If
successful activation was durably recorded but either installed file update
failed, startup finishes both file updates without another activation. Until recovery completes, the
installed `.env` and Compose file may describe different releases; use
`beta_start` to recover before running manual Compose commands. Do not delete
or edit the journal to bypass recovery. If activation finished just before its
completion record failed, its outcome is uncertain and startup repeats the same
candidate release cycle. It never infers success from an incomplete record.

To replace a failed activation with a forward repair or same-schema rollback,
pass an explicit `--release` manifest (and `--rollback` for a rollback). This
preserves host settings from the pending attempt and starts a new attempt;
previous attempt files remain available for inspection. If completion was
already recorded, startup first finishes its installed file updates. A normal
start with no pending journal still performs a fresh release cycle.
These files are release inputs, not database backups. Use the [backup runbook](beta-data-lifecycle.md) for data.
The Compose file is managed from the release commit; make topology changes in
the repository, not in the installed copy. All commands use the existing
`polybot` project, so use one installation per Docker host and do not run the
manual release tool concurrently. Automated starts in the same app directory
are protected by a deployment lock.

For subsequent releases, keep the original infrastructure digests by supplying
their exact values from the previous manifest to the publisher's
`--postgres-image` and `--redis-image` options. Copy the new manifest, fetch the
new source commit on the server, then run:

```sh
uv run python -m scripts.beta_start \
  --username YOUR_GITHUB_USER --release "$HOME/polybot-release-2.env"
```

Startup validates the complete runtime manifest, including SMTP settings, before
Docker operations. Image repository syntax follows
[Docker Distribution references](https://github.com/distribution/reference/blob/main/regexp.go).
Manifests must be regular files; the installed `.env` must
have mode `600`. Startup preserves the host's settings/secrets and refuses
infrastructure digest changes; those need the separate maintenance plan described above. For a
same-schema rollback, pass the previous image manifest with `--rollback`.
No schema downgrade runs. The lower-level release tool also accepts
`--compose-file "$HOME/app/docker-compose.yml"` when working with installed files.

For later log inspection without redeploying:

```sh
docker compose --project-name polybot --env-file "$HOME/app/.env" \
  -f "$HOME/app/docker-compose.yml" logs --follow --tail 100
```

The actual frontend is a static Svelte build served by Caddy. These commands
retain the existing TLS configuration, loopback-only ingress and paper-only
execution. They do not add the pasted conversation's proposed Cloudflare Tunnel
or change memory/process budgets. For the default private origin, access from
the main laptop using `ssh -N -L 8443:127.0.0.1:8443 SERVER_USER@SERVER_HOST`, then
open `https://localhost:8443` with the certificate trusted by that browser.
Public opening still requires the existing beta acceptance gates.

Test the automation without registry pushes or retained deployment changes:

```sh
uv run pytest backend/tests/control_plane/test_beta_host_deployment.py \
  backend/tests/control_plane/test_deployment.py \
  backend/tests/control_plane/test_beta_backups.py \
  backend/tests/control_plane/test_reliability_deployment_contract.py \
  backend/tests/control_plane/test_auth.py \
  backend/tests/control_plane/test_account_mail.py
```

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
preserved and interrupted runs require a new launch. The initial migration includes
reliability metadata. The September 10 local consolidation requires recreating old
disposable databases; future retained deployments use forward migrations and only
schema-compatible rollback releases. During a database outage recovery waits for the database,
and Redis outages keep queue entries durable. See the architecture's Slice 18
section for lease, I/O and shutdown bounds. Open signup remains gated.

Slice 19 requires SMTP configuration in the release manifest and runtime SMTP
credential files, available only to the API service. See [account recovery](account-recovery.md).
Production API startup refuses missing or invalid mail configuration; relay outages
produce a retryable generic delivery failure without blocking sign-in. Recovery
state is included in the initial migration and requires a matching schema-aware release. Browser
acceptance captures mail in a short-lived disposable sink; traces are disabled so
passwords and link tokens are not retained in test artifacts.

Slice 20's independent operational monitor runs alongside recovery and logs
structured alerts. Workers publish process presence separately from job leases.
Recovery mounts the PostgreSQL volume read-only only for filesystem-capacity
measurement. See [beta operations](beta-operations.md) for incident admission,
account suspension and OS-authorized diagnostics; no operator HTTP route is added.

The final public-opening checklist and contact prerequisites are in
[beta launch](beta-launch.md); completing these procedures does not itself open signup.
