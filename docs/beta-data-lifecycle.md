# Beta backups and data lifecycle

These approved beta policies apply to the single-host paper deployment. They do
not open public signup. The operator name and support contact remain placeholders
until Slice 23's release gate is completed; the deployment owner is responsible
for these procedures.

| Data / objective | Policy |
| --- | --- |
| Database backup | Daily encrypted age archive on a protected off-host mounted destination |
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
history can be observed. Active runs, saved bots and graph revisions are not
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
removes events, runs, graph revisions, bots, private graph templates, credentials
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

Install `age` and the repository's pinned Python environment on the Linux host.
Select a local Docker context without `DOCKER_HOST`/`DOCKER_CONTEXT` overrides.
Backup/restore validates and pins its Unix socket for the whole workflow; remote
TCP/SSH contexts are rejected. See [Docker context behavior](https://docs.docker.com/engine/manage-resources/contexts/).
Mount protected off-host storage at `/mnt/polybot-backups`, owned by the service
operator with mode 0700. Keep its access credentials in the host secret store.
Generate the age private identity on the recovery operator's protected system;
store it separately from the host and backup destination. Install only its public
recipient lines at `/etc/polybot/backup-recipients.txt`. Record recovery custody
and test that a second authorized operator can retrieve the identity.

Install `deploy/systemd/polybot-backup.{service,timer}` and
`deploy/systemd/polybot-backup-check.{service,timer}` in `/etc/systemd/system`.
The units assume `/srv/polybot`, `/usr/local/bin/uv`, and the active pinned release
manifest `/etc/polybot/release.env`; adapt these explicit host paths when installing.
Enable both timers with `systemctl enable --now polybot-backup.timer polybot-backup-check.timer`. Start `polybot-backup.service` immediately and inspect
its exit status before relying on the schedule. The daily timer is 02:00 UTC and
catches missed executions after reboot. The hourly check fails if no completed
checksum-valid completed archive satisfies the 24-hour recovery point. Both services
assert that the destination is mounted and fail if it is only a local directory. The deployment owner must monitor
failed units and the journal and repair a missed backup immediately. Configure
host failure notification to the release checklist's real support owner before
public opening.

Manual invocation, using the same pinned release:

```sh
uv run python -m scripts.beta_backup create /etc/polybot/release.env --project polybot --directory /mnt/polybot-backups --recipients /etc/polybot/backup-recipients.txt
uv run python -m scripts.beta_backup check --directory /mnt/polybot-backups
```

The pipeline uses the database image's `pg_dump` custom format and streams directly
into age. Only successful dump and encryption exit codes publish an fsynced,
atomically renamed archive. The completed filename binds the snapshot start time
and `sha256` digest of the encrypted bytes. Recovery-point checks recompute this
digest to detect truncation/bit rot; incomplete, malformed, future-dated or corrupted
archives do not satisfy the check. Directory permissions protect the trusted
completion record: this checksum is not a substitute for age authentication or a
restore rehearsal, and the private decryption identity is never installed for the
hourly check.
Retention deletes only completed, conventionally named archives older than the
policy; do not create untracked copies. A successful dump is not a restore test.
The implementation follows [PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html),
[pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html) and the
[age command-line interface](https://github.com/FiloSottile/age).

## Restore without reopening old access

Use an isolated host/network with enough disk space for PostgreSQL and the dump.
Retrieve the matching release manifest and immutable image IDs, the encrypted
archive and separate private age identity. Restore the required runtime secrets
from the secret store. The scratch directory must be mode 0700 on encrypted disk
or tmpfs; its temporary plaintext file is unlinked on completion/failure. The
identity must have no group/other permissions.

```sh
uv run python -m scripts.beta_backup restore /etc/polybot/release.env /mnt/polybot-backups/ARCHIVE.dump.age --identity /secure/recovery.age --scratch-directory /secure/restore-scratch
```

This verifies the entire encrypted stream before touching PostgreSQL, generates a
new isolated Compose project, starts only PostgreSQL/empty Redis, restores in one
transaction and quarantines the database using the matching backend image. All
identities receive a separate restore-quarantine flag, original suspensions remain,
all sessions/account tokens are removed, all previous jobs become terminal and
admissions remain paused. No API, worker, recovery daemon or ingress is started.
A failure leaves the destination closed; inspect and remove the disposable project
before retrying. Never point `pg_restore` at a running deployment.

Compare accounts and ownership, bots, immutable graph revisions and retained run
history to the backup inventory. Do not interpret a successfully restored snapshot
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
docker compose --project-name RESTORED_PROJECT --env-file /etc/polybot/release.env -f deploy/compose.yaml run --rm --no-deps --entrypoint python recovery -m api.lifecycle approve-restored-account USER_UUID --reconciled-against-current-records
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
and SMTP/database/TLS secrets through a separately encrypted secret/configuration
store with the same recovery availability and access controls. Do not place the
age private identity next to archives. The browser service needs no uploaded files
or local market recordings. Redis contains queues, leases/rate counters and live
telemetry; restore it empty and accept transient counter resets under paused
admissions. Caddy state is replaceable from the managed TLS/configuration source.
Source code and built images remain in their versioned repository/image registry.

Users can export their private graph JSON before deletion through the existing
editor download. There is no full-account self-service export. Until a real support
address is configured, an authenticated operator-assisted export is a manual beta
procedure: verify account ownership through the existing signed-in account and
verified email flow, select only that owner’s bots/revisions and retained runs,
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
