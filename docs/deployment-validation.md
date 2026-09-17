# Deployment simplification validation

Recorded September 13, 2026 against the implementation and style-review working tree.
Frontend/browser results are retained from the original implementation; this
review changes deployment tooling and backend tests, and reruns the Python and
deployment checks below. No production
tag, image publication, retained-host deployment or account configuration was
performed. Operational setup remains pending the external acceptance checklist in
[the deployment runbook](beta-deployment.md#acceptance-and-removal-inventory).

## Completed repository checks

| Check | Observed result |
| --- | --- |
| Full Python suite with fresh disposable PostgreSQL and Redis | 1,820 passed, no skips, 77.31 seconds |
| Frontend unit/component suite | 398 passed across 48 files |
| Svelte diagnostics | Zero errors and warnings |
| Generated API client parity | Passed |
| Frontend production build and Python wheel/source distribution build | Passed |
| GitHub actionlint and all six Ansible playbook syntax checks | Passed |
| Ruff on changed Python files and whitespace diff check | Passed |
| Real HTTPS deployment/browser rehearsal | Passed login, cookies, CSRF/origin, proxy trust/spoof resistance, email origin, ownership, queueing, Stop, reload/SSE, worker loss, release and rollback |
| Encrypted backup through real rclone SFTP and isolated restore | Passed; restore took 7.3 seconds, retained accounts/ownership/bots/history, and launched no jobs |
| Disposable Debian bootstrap twice | Passed; second pass changed=0, database credential, running container and volume retained |
| Detached systemd operation after SSH client loss | Passed |
| Real Ansible, installed executor, systemd and Compose activation | Deploy, rollback, healthy retry, migration/rollback failure, recovery, conflicting bundle and HTTPS failure paths passed |
| Installed msmtp delivery through disposable authenticated STARTTLS SMTP | Failure, suppression, failed-send retry and recovery verified |

The Python run emitted existing Starlette/httpx and multithreaded-fork deprecation
warnings. The latest style-review report is `data/code-style-deployment-review/full-pytest.xml`; rehearsal command logs
and restore results are under ignored `data/beta/`. These are local evidence, not
published release artifacts. Focused remote-backup and monitor tests were rerun
after final cleanup and passed.

Release tests cover strict version tags, ancestry/workflow gates, digest manifests,
bundle source/hash validation, moved/conflicting provenance, draft/partial release
rejection, complete-bundle reuse and serialization. Executor tests cover first
installation, update, healthy no-restart retry, image pull failure, migration
failure, incompatible rollback, locks, durable promotion interruptions and explicit
repair. Remote tests cover unavailable SFTP, incorrect host keys, partial uploads,
corrupt archive/bundle bytes, missing matching bundles, stale snapshots and bounded
retention of recognized artifacts. Monitor regressions require every service/timer
to be active, reject failed backup units, suppress identical alerts, report recovery
and retry SMTP delivery failures.

## Reproduction

Install the development dependencies and supply disposable PostgreSQL/Redis URLs
as `POLYBOT_TEST_POSTGRES_URL` and `POLYBOT_TEST_REDIS_URL`, then run:

```sh
uv run pytest --junitxml=data/automation-tests.xml
npm --prefix frontend test
npm --prefix frontend run check
npm --prefix frontend run generate:check
npm --prefix frontend run build
uv build
actionlint
```

Run the three disposable integration commands listed in the deployment runbook.
The reusable account workflow also retains the existing multi-account browser
suite; this implementation's browser execution used the private deployment suite.

## Fixture limits and pending activation

The HTTPS fixture terminates local TLS before the production Caddy HTTP path.
It cannot prove real Tailscale Serve identity, certificate issuance/renewal, policy,
or reboot persistence. The Debian container skips the account-dependent tailnet
block; its nested Docker daemon uses test-only vfs storage to avoid overlay nesting.
The SMTP fixture proves authenticated STARTTLS and actual host alert delivery
through the rendered msmtp configuration, including suppression, retry and recovery.
It does not prove acceptance by the supplied production relay. The backup rehearsal
uses a fully verified release bundle built from the working tree for this disposable
fixture, then calls the host backup CLI and restores the downloaded pair in
quarantine. Real publication continues to require committed source provenance.
The Debian activation rehearsal runs the actual Ansible, installed Python executor,
systemd units and Docker Compose with small fixture service images. Registry login
and the account-dependent HTTPS endpoint are substituted locally; deployment,
rollback, failure/retry and journal/pointer behavior execute unchanged.

Both amd64 and arm64 are supported configuration targets; the actual target's
architecture, capacity, network routing and reboot behavior still require recorded
acceptance. Real GitHub publication/reuse and permissions, ephemeral WIF enrollment
and cleanup, SSH/HTTPS-only policy, independent unreachable-host notifications,
Serve, provider SMTP, the supplied SFTP host key/directory and offline-identity
restoration remain external checks. No free-tier limit was upgraded or purchased.

## Final documentation-drift audit

README, deployment, both architecture references, operations, data lifecycle and
the affected implementation-plan records were compared with the delivered commands,
workflow inputs, inventory, units, proxy configuration and backup/recovery behavior.
References to removed publisher/setup/start/registry/Git/TLS helpers remain only in
the explicit removal inventory. No operational instructions require a backup mount,
manual certificate copies or the superseded startup commands. External HTTPS and
internal HTTP ports are documented separately; remote checksum verification is the
recovery-point gate. Durable recovery, schema-compatible rollback, restore
quarantine, application authentication and paper-only restrictions remain explicit.
No unresolved documentation drift was found. There are no product-plan deviations;
the fixture substitutions above are intentional validation limits. No Polymarket
protocol or SDK integration changed, so a new PolymarketDocs check was not required.

## Deployment style-review follow-up

The explicitly requested review ran all 51 repository rules and reconciled every
report before implementation, then reran the 43 affected rules and focused closing
checks. Release bundles, activation, SFTP transport/inventory and host operations
now have semantic owners and typed boundary contracts. Invalid current pointers,
image provenance, malformed persisted inputs and unavailable dependencies fail
visibly. Bootstrap validates private inputs before host mutation. Static Compose,
Caddy and workflow values are checked against their Python owners; rendered Ansible
configuration is validated against its consumers. SMTP remains at-least-once with
possible duplicates after uncertain relay acceptance.

The documentation-drift audit also checked normalized inventory output, HTTP port
in operations.json, controller prerequisites, cadence and polling budgets, package
ownership and fixture boundaries. No external deployment or Polymarket protocol
change is included in this maintenance pass.


## Optional SFTP backup setup — September 14, 2026

The deployment follow-up adds an explicit `polybot_backups_enabled` opt-out.
Verification from the repository root:

```sh
uv run pytest backend/tests/control_plane/test_optional_backups.py backend/tests/control_plane/test_deployment_preflight.py backend/tests/control_plane/test_deployment_contracts.py backend/tests/control_plane/test_host_monitoring.py backend/tests/control_plane/test_beta_host_deployment.py backend/tests/control_plane/test_release_automation.py backend/tests/control_plane/test_deployment_boundaries.py backend/tests/control_plane/test_backup_boundaries.py backend/tests/control_plane/test_remote_backups.py
PYTHONPATH=backend/tests uv run python -m control_plane.bootstrap_rehearsal
```

The focused suite passed **247 tests**. It covers omitted SFTP inputs on explicit
opt-out, strict boolean configuration, enabled-by-default compatibility, retained
credential validation when enabled, rendered operational configuration, continued
application monitoring, and refusal of disabled manual backup operations. Ruff
and Ansible backup-playbook syntax checks passed. A manual `backup.yml` invocation
against the disposable Debian fixture with backups disabled failed at the explicit
input guard with zero host changes, before starting a snapshot.

The disposable Debian/systemd rehearsal also passed: fresh bootstrap without any
SFTP or age inputs, a second pass with zero changes, backup timer
enable/disable/re-enable transitions with monitoring retained, credential
preservation, detached activation, migration/rollback failures and retries, private
HTTPS failure/retry, and authenticated STARTTLS alert delivery. Local logs are under
`data/beta/polybot-bootstrap-test-866f4e01a7/` (git-ignored).

Final documentation-drift audit: README, deployment and operations guides, data
lifecycle recovery assumptions, both architecture references, inventory examples
and the implementation plan describe the same optional behavior. Disabled mode
provides no scheduled snapshots, retention or recovery-point coverage. Enabled
backup encryption, remote verification and retention are unchanged. No Polymarket
protocol/SDK integration changed, so no PolymarketDocs check was required. Actual
production tailnet, SMTP and enabled-backup recovery acceptance remain operator
checks; no production host was changed during verification.

## Ansible host preparation — September 17, 2026

Host policy now belongs to Ansible bootstrap; the standalone preparation script
and separate guide have been retired. Follow the first-access and bootstrap
instructions in [the deployment runbook](beta-deployment.md). Verification from
the repository root:

```sh
uv run pytest backend/tests/control_plane/test_server_preparation.py backend/tests/control_plane/test_deployment_contracts.py backend/tests/control_plane/test_deployment_preflight.py backend/tests/control_plane/test_optional_backups.py
ANSIBLE_CONFIG="$PWD/deploy/ansible/ansible.cfg" uv run ansible-playbook -i deploy/ansible/inventory/production.example.yml deploy/ansible/bootstrap.yml --syntax-check
PYTHONPATH=backend/tests uv run python -m control_plane.bootstrap_rehearsal --host-only --initial-access su
```

The focused suite passed **148 tests**, including strict host-policy inputs,
fresh key-only SSH and sudo proof, required remote identity, effective SSH policy
conflicts, idempotent SSH templates, and the actual Ansible swap filesystem,
existing-file and fstab guards. Changed Python files passed Ruff; the bootstrap
playbook passed Ansible syntax checking.

A subsequent production report exposed a gap in the original fixture: it supplied
host settings explicitly, so it did not catch the normalized dictionary being
stored under `set_fact`'s `_raw_params` rather than installed as individual facts.
The handoff now sets each validated key/value explicitly. Two local Ansible
regressions execute the actual validation task file with omitted and explicit host
settings, checking every normalized value, including nulls, booleans and hostname
normalization. They perform no server mutation. This correction preserves the
documented defaults; an omitted administrator is valid.
The focused suite passed **150 tests** after the correction, and bootstrap syntax
checking passed. Documentation-drift audit: the runbook still describes the same
optional/default behavior; its troubleshooting table now identifies this handoff
bug. The local laptop inventory explicitly retains the requested lid-ignore policy.

A further production run exposed the delegated SSH proof's working-directory
assumption: Ansible starts local commands in the playbook directory, so the
inventory's `./known_hosts` was resolved outside the repository root. The SSH
subprocess now explicitly runs from the repository root. Two local Ansible
regressions import the actual proof task and substitute a recording SSH executable
to verify its working directory, relative key/known-hosts arguments and inventory
versus command-line hostname selection. A controller test checks that SSH failures
produce an actionable diagnostic without exposing subprocess output.
The focused suite passed **153 tests**, Ruff passed, and bootstrap syntax checking
passed. The corrected proof task also passed a read-only connection to the actual
server using the existing SSH agent, verifying `polybot` and passwordless root
sudo; the full production bootstrap was not rerun. Documentation-drift audit:
the runbook now states the relative-path base and documents this failure.

A disposable Debian/systemd rehearsal passed first bootstrap through root SSH
on an image without Python or sudo, followed by a second run as `polybot` with
**changed=0**. It also passed retained container/volume/credential checks, backup
enable/disable/re-enable, detached systemd execution, release activation/failure/
retry, and authenticated STARTTLS alert delivery. Logs for that full run are in
`data/beta/polybot-bootstrap-test-b99a1275b7/` (git-ignored).

The focused `--host-only --initial-access su` rehearsal also passed on a fresh
minimal image. It repaired a legacy Tailscale source before installing Python/sudo,
bootstrapped through the human account using the root password, and repeated as
`polybot` with **changed=0**. Real systemd, UFW, fail2ban, update timers, sudo-group
membership and the logind drop-in were checked. Root SSH was rejected; a wrong
deployment key stopped before SSH file mutation; a conflicting user Match rule
triggered the Ansible rescue path, restored both SSH files and reloaded sshd.
Logs are in `data/beta/polybot-bootstrap-test-b485ffcb5b/` (git-ignored).

Swap is deliberately unmanaged in the container: its overlay filesystem and shared
kernel cannot establish actual host swap safety. Laptop lid behavior, kernel swap
activation, reboot persistence, target firewall routing and real Tailscale
enrollment/Serve remain target-host acceptance checks. No production host was
changed. Final documentation-drift audit: README, architecture, implementation
plan, example inventory and deployment runbook agree on Ansible ownership,
root/sudo/su first access, optional lid/swap settings, the verified SSH transition,
and Tailscale's route-dependent ordering. No application contract or Polymarket
protocol/SDK code changed; no PolymarketDocs check was required.

## CI regression follow-up — September 17, 2026

The legacy repository recovery test now executes bootstrap's current raw-shell
repair before the Python/sudo APT task. It verifies backup preservation, unrelated
entries, absent files and repeat-run idempotency using temporary files only.
Recording trim assertions tolerate Rich folding filenames across panel lines.
Graph editor coverage creates and reopens each operation in a separate test,
retaining the default timeout without growing one canvas through the full catalog.

The disposable HTTPS/browser rehearsal passed locally. The reported CI browser
failure could not be identified from its retained log: subprocess output was
written only to the runner's local `commands.log`. Failed rehearsal commands now
also print that output after the existing credential-disclosure check, with
regressions covering exit status and rejection of sensitive output. Its original
CI-only browser cause remains unconfirmed until a diagnostic rerun.

Verification: `uv run pytest` passed **1,884 tests with no skips** against fresh
disposable PostgreSQL/Redis; `npm --prefix frontend test` passed **419 tests**;
`npm --prefix frontend run check` reported zero errors and warnings. The full
`PYTHONPATH=backend/tests uv run python -m control_plane.deployment_smoke` command
passed locally. Changed Python files passed Ruff and the diff passed whitespace
checks. Existing Starlette/httpx and fork deprecation warnings remain.

Documentation-drift audit: this follow-up changes test coverage and rehearsal
diagnostics only. Host preparation, trim behavior, application contracts and the
implementation-plan scope remain unchanged; no PolymarketDocs check was required.
