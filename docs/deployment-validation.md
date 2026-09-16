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

## Standalone server preparation — September 17, 2026

The pre-Ansible entrypoint is `scripts/prepare-server.sh`; follow
[server preparation](server-preparation.md) before the deployment runbook.
Verification from the repository root:

```sh
bash -n scripts/prepare-server.sh
shellcheck scripts/prepare-server.sh
uv run pytest backend/tests/control_plane/test_server_preparation.py
```

All **20 tests** passed. They exercise redirected temporary files and substituted
host commands: SSH syntax/policy/reload rollback, repeatable Include placement,
active-swap persistence repair, unsafe existing swap rejection, insufficient disk,
fstab conflicts, SSH rules before firewall enablement, firewall failure, retained
Tailscale identity, first enrollment, and pending device approval. Bash syntax,
ShellCheck and the changed test file's Ruff checks passed.

A separate disposable Debian container exercised real `sshd -t`/`sshd -T`,
precedence over an earlier cloud drop-in, a second unchanged hardening pass, a
successful non-root key-only SSH connection, root rejection with the same installed
key, and configuration rollback for a conflicting user Match rule. Service reload
was substituted in that container; this does not establish real systemd reload or
end-to-end host preparation. No production host was changed.

Actual lid behavior, kernel swap activation/reboot persistence, firewall routing,
systemd timers, and browser enrollment in the intended tailnet remain target-host
checks in the setup guide. Final documentation-drift audit: README, architecture,
implementation plan and deployment runbook agree on preparation before Ansible,
the administrator/sudo prerequisites, manual Tailscale tagging after browser login,
and the current Vault requirement. The runbook's stale Vault template path was
also corrected. No application contract or Polymarket protocol/SDK code changed;
no PolymarketDocs check was required.
