# Beta backups and data lifecycle

These approved beta policies apply to the single-host paper deployment. They do
not open public signup. The operator name and support contact remain placeholders
until Slice 23's release gate is completed; the deployment owner is responsible
for these procedures.

| Data / objective | Policy |
| --- | --- |
| Database backup | When enabled: daily encrypted age archive transferred and verified through SFTP |
| Backup expiry | 14 days; no indefinite archive |
| Recovery point | At most 24 hours before an incident |
| Recovery time | At most 2 hours for an isolated restore and quarantine; reopening requires reconciliation |
| Run history | Up to the latest 100 terminal runs per account, at most 30 days after completion (creation for historical rows without completion) |
| Active runs | Preserved until terminal; existing global execution, event-rate and storage-admission limits apply |
| Account deletion | Quiesce immediately; remove eligible account data within 24 hours |
| Operator audit and completed deletion receipts | 90 days; operator records contain actor/action/outcome/opaque target ID/timestamp; deletion receipts contain owner UUID and request/completion timestamps |

Approved beta policy: encrypted backups every 24 hours, retained 14 days; recovery point ≤24 hours and isolated restore ≤2 hours; up to 100 terminal runs per account for 30 days; immediate deletion quiescence and eligible erasure within 24 hours; minimal completed deletion receipts and operator audits retained 90 days.

<!-- lifecycle-policy:start -->
| Policy | Value |
| --- | ---: |
| Backup interval hours | 24 |
| Backup retention days | 14 |
| Recovery-point target hours | 24 |
| Isolated restore target hours | 2 |
| Retained terminal runs per account | 100 |
| Terminal history retention days | 30 |
| Deletion target hours | 24 |
| Completed receipt / audit retention days | 90 |
| Maintenance interval seconds | 60 |
| History / per-account purge run batch | 25 |
| Event deletion batch per selected run | 5000 |
| Account deletion batch | 10 |
| Audit / completed receipt batch | 1000 |
| Deletion quiescence seconds | 60 |
<!-- lifecycle-policy:end -->

History is hidden at the age/count boundary. Cleanup runs every minute in the
supervised recovery process, removes at most 25 terminal runs per pass and 5,000
events per selected run, and commits an expiry marker before partially removed
history can be observed. Active runs and saved bots are not
removed by history expiry. Old run URLs return the same private not-found response
as inaccessible resources. Launch deduplication keys expire with their retained
run. Browser retries send `Idempotency-Recovery: true` with their stored key:
missing or expired history returns 410 and cannot create a replacement run. The
browser asks the user to review retained history before a new explicit Run action.
API clients must also distinguish recovery from new launch intent using this header;
legacy key-only deduplication remains bounded by retained history.

Account deletion is available under Account. It requires the current password
and explicit browser confirmation, accepts no target account ID, atomically blocks
admissions, revokes all sessions/recovery links and terminates paper jobs. Workers
must retain their database execution lease for every write/fill; stale deliveries
cannot recreate purged rows. After a 60-second quiescence interval, bounded cleanup
removes events, runs, bots, credentials
and the identity in dependency order. Retry is safe. Requests remain blocked even
if cleanup fails; ordinary operator Resume cannot cancel deletion.

The 24-hour target requires healthy maintenance and sufficient capacity. Inspect
`data_maintenance_failed` operation observations and the recovery service journal
on every failure. Fix the dependency and run `python -m api.lifecycle clean` using
the private recovery container command below; repeat bounded passes until the
backlog clears. Do not resume a deletion-requested account to troubleshoot it.
Pending requests are retained until completed, then the minimal receipt expires
90 days later. Immutable backups can contain deleted data until their 14-day
expiry; they are never used to serve archived history.

## Install automated backups

SFTP backups can be disabled with `polybot_backups_enabled: false` during private
setup. This disables scheduled snapshots, remote retention and backup freshness
monitoring; it does not create local replacement backups. The recovery objectives
above require backups to be enabled and verified. Existing remote archives and
staging files remain untouched on opt-out; manage their expiry separately while
automated retention is off. See [optional backups](beta-deployment.md#optional-sftp-backups)
for enabling later and the required SFTP/age inputs.

Follow the single [bootstrap checklist](beta-deployment.md#one-time-setup).
With backups enabled, Ansible installs age, rclone, msmtp, private staging and
starts daily/hourly systemd timers.
Use one dedicated SFTP application directory and independently verified host keys;
`known_hosts_file` is mandatory. No mount, TOFU, remote shell hashing or custom SFTP
transport is used. The age private identity stays on the protected recovery
machine; only public recipients are installed under `/srv/polybot/secrets`.

Daily snapshots use the pinned PostgreSQL image's custom-format `pg_dump` streamed
into age. Both processes must complete before local publication. Canonical names
bind snapshot start time and the encrypted `sha256` digest. rclone uploads the
matching non-secret release bundle and encrypted archive, reads both back and
compares their checksums. Only then is off-server success reported and local
staging cleaned. Hourly checks independently read remote bytes; incomplete,
corrupted, future-dated or stale snapshots and missing/corrupt bundles cannot
satisfy the 24-hour recovery point. An SFTP error fails closed. Checksums detect
storage damage; age authentication and restoration acceptance remain necessary.

Retention deletes only canonical archive/bundle artifacts at the 14-day boundary
within the configured application directory, including recognized rclone upload
partials after interruption. It never mirror-deletes arbitrary
files. Host staging retains at most two failed snapshots and removes stale
incomplete files. Backup and activation share the deployment lock so the dump and
retained bundle describe the same active release. The host needs a local Docker
Unix socket; ambient Docker context overrides are rejected.

The routine operator command is Ansible `backup.yml`. Underlying commands used by
the tooling, shown for recovery diagnostics with the same private configuration:

```sh
python -m scripts.beta_backup create /srv/polybot/.env --directory /srv/polybot/staging --recipients /srv/polybot/secrets/age-recipients.txt --config /srv/polybot/secrets/rclone.conf --remote backup:/YOUR_APPLICATION_DIRECTORY --bundle /srv/polybot/current/release.tar.gz
python -m scripts.beta_backup check --directory /srv/polybot/staging --config /srv/polybot/secrets/rclone.conf --remote backup:/YOUR_APPLICATION_DIRECTORY
```

Use `current/.venv/bin/python` from the active bundle directory. Host timer failures
and recoveries are emailed through msmtp; detailed diagnostics stay in journald.
The daily calendar derives from the 24-hour policy and catches missed runs after
boot; hourly freshness checks detect overdue recovery points.
[rclone SFTP host verification](https://rclone.org/sftp/#host-key-validation),
[PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html),
[age](https://github.com/FiloSottile/age).

## Restore without reopening old access

Use an isolated host/network with enough disk space for PostgreSQL and the dump.
Download and verify the archive and its matching retained release bundle into a
new mode-0700 directory on the recovery machine:

```sh
python -m scripts.beta_backup download ARCHIVE.dump.age --directory /secure/download --config /secure/rclone.conf --remote backup:/YOUR_APPLICATION_DIRECTORY
```

This prepares verified source under `/secure/download/release`. Install its locked
environment with `uv sync --locked --no-dev --directory /secure/download/release`.
Combine its `images.env` with separately restored origin/SMTP/path configuration
into `/secure/restore.env` (mode 600). Use isolated runtime secrets and preserve
its pinned images. Keep the separate private age identity on this recovery machine. Restore the required runtime secrets
from the secret store. The scratch directory must be mode 0700 on encrypted disk
or tmpfs; its temporary plaintext file is unlinked on completion/failure. The
identity must have no group/other permissions.

```sh
python -m scripts.beta_backup restore /secure/restore.env /secure/download/ARCHIVE.dump.age --identity /secure/recovery.age --scratch-directory /secure/restore-scratch
```

This verifies the entire encrypted stream before touching PostgreSQL, generates a
new isolated Compose project, starts only PostgreSQL/empty Redis, restores in one
transaction and quarantines the database using the matching backend image. All
identities receive a separate restore-quarantine flag, original suspensions remain,
all sessions/account tokens are removed, all previous jobs become terminal and
admissions remain paused. No API, worker, recovery daemon or ingress is started.
A failure leaves the destination closed; inspect and remove the disposable project
before retrying. Never point `pg_restore` at a running deployment.

Compare accounts and ownership, bots and retained run history with complete configuration snapshots to the backup inventory. Do not interpret a successfully restored snapshot
as permission to reopen any identity: changes after its recovery point are absent.
Reconcile **each identity** against current deletion requests, suspension/audit
records and authenticated support records kept outside the failed snapshot. If
these records cannot be established, leave the identity quarantined. First apply
missing deletion/suspension requests through the private operator procedure; never
approve an account known to be deleted or suspended. The approval command requires paused admissions and an actual quarantine marker,
and refuses any suspension or deletion receipt already present. Repeating approval
fails once its marker is cleared, so a skipped quarantine cannot look like success.
Each explicit global quarantine invocation safely closes all access and records an
operator audit, including retries; existing quarantine timestamps are preserved.
It is an emergency closure command, not a queued job or automatic restore retry.

For each reconciled eligible account, run `python -m api.lifecycle approve-restored-account`
with its identity and reconciliation flag, using the returned isolated project name:

```sh
docker compose --project-name RESTORED_PROJECT --env-file /secure/restore.env -f deploy/compose.yaml run --rm --no-deps --entrypoint python recovery -m api.lifecycle approve-restored-account USER_UUID --reconciled-against-current-records
```

Use the same private command form with `python -m api.lifecycle clean` for maintenance.
The initial closure command is `python -m api.lifecycle quarantine-restore`; it is
normally invoked by the restore workflow, before application startup. Approval is audited
under the container's effective OS actor. Reopening admissions and services is a
separate incident decision in `beta-operations.md`; new explicit user Run actions
are required, and original jobs are never resumed. Destroy abandoned restore
projects and their volumes after the rehearsal.

## Non-database files, export and support

Preserve release manifests, immutable image references, environment configuration
and SMTP/database/SFTP secrets through a separately encrypted secret/configuration
store with the same recovery availability and access controls. Do not place the
age private identity next to archives. The browser service needs no uploaded files
or local market recordings. Redis contains queues, leases/rate counters and live
telemetry; restore it empty and accept transient counter resets under paused
admissions. Caddy state is replaceable; Tailscale Serve recreates managed certificates.
Source code and built images remain in their versioned repository/image registry.

Users can export their private graph JSON before deletion through the existing
editor download. There is no full-account self-service export. Until a real support
address is configured, an authenticated operator-assisted export is a manual beta
procedure: verify account ownership through the existing signed-in account and
verified email flow, select only that owner’s bot configurations and retained runs,
exclude password hashes/session or recovery secrets and third-party account data,
and deliver through an agreed private channel. Do not retain an export indefinitely
or promise recovery after erasure. Public opening is blocked while support contact,
ownership, protected storage, recovery key custody or notification routing is unset.

## Disposable acceptance

Run the real backup/restore rehearsal on disposable Docker projects only:

```sh
PYTHONPATH=backend/tests uv run python -m control_plane.backup_rehearsal
```

It builds the current pinned deployment, creates two accounts and owned graph/run
history through HTTPS fixtures, encrypts an actual PostgreSQL backup and restores
into a distinct project. It compares counts and content digests, checks all access
is quarantined and credentials are gone, confirms only PostgreSQL/Redis run, records
measured restoration time in `data/beta/*/restore-result.json`, and removes both
projects/volumes. Run it after schema or backup changes and before release; compare
its measured result with the two-hour target. Unit/real-service lifecycle tests
cover retention boundaries, partial-batch rollback/retry, account isolation,
deletion/launch serialization and delayed worker writes after purge.

The final public-opening checklist and contact prerequisites are in
[beta launch](beta-launch.md); completing these procedures does not itself open signup.
