# Private deployment and release operations

Use GitHub Actions, Ansible and Docker Compose on one Debian host, amd64 or
arm64. Tailscale Personal supplies private connectivity and Serve HTTPS. The API
keeps its own email/password authentication. The application remains paper-only;
no public-opening gate or live-trading opt-in is changed.

## One-time setup

Run these steps in order. Account creation and credentials are operator inputs;
no automation buys capacity, upgrades a plan or enables Funnel.

1. Obtain a Debian 12/13 host with initial OpenSSH access and a sudo-capable account.
   The staging baseline is four CPUs, 8 GiB RAM and 40 GiB free disk; repeat capacity
   acceptance on the actual host. Verify the host's SSH public key through its
   console/provider channel. Do not trust an unauthenticated `ssh-keyscan` result.
2. Use a Tailscale **Personal** tailnet. Enable MagicDNS and HTTPS in its admin
   console. Set the intended machine name before selecting the exact
   `https://HOST.TAILNET.ts.net` origin. Merge `deploy/tailscale-policy.example.hujson`
   into policy, removing broader grants that would give CI additional access.
   Tag only this deployment host `tag:polybot`; CI has only TCP 22 and 443 to it.
   Create a one-time tagged host enrollment key. Never enable Funnel.
3. Install OpenSSH (`ssh-keygen`) on the controller. Install Python controller
   tools with `uv sync --locked --extra dev` and
   `uv tool install ansible-core==2.19.7`. Generate a deployment SSH key.
   **SFTP backups are optional:** the example inventory sets
   `polybot_backups_enabled: false`, so you can continue without SFTP storage,
   backup credentials, `age` on the controller, or an age recovery identity.
   To enable backups, set `polybot_backups_enabled: true`, install `age` on the
   controller, and fill the commented SFTP inventory and secret values. Obtain
   the SFTP server's public host key through a trusted channel. Create a dedicated
   existing storage directory and SSH key with read/write/delete rights there;
   keep storage ownership outside automation. Generate `age-keygen -o recovery.age`
   on the protected recovery machine; copy only `age-keygen -y recovery.age` public
   output to `polybot_age_recipients` in the public inventory. Keep the private
   identity offline, outside the host and SFTP storage.
4. Copy `deploy/ansible/inventory/production.example.yml` to
   `deploy/ansible/inventory/production.yml`. This file contains the non-secret host,
   architecture, root, origin and operational configuration, including the deployment
   SSH public key and SMTP username. Default root:
   `/srv/polybot`. Fill every example value. Keep a `known_hosts` file at
   the repository root, with verified keys for both the initial address and
   tailnet hostname. Create `deploy/ansible/inventory/production.vault.yml` from
   `secrets.example.yml` using the Vault commands below, then replace every required
   value with `ansible-vault edit` (backup secrets only when enabled). Commit both
   `production.yml` and the encrypted `production.vault.yml`; keep plaintext secrets
   and the Vault password out of Git. Use the public/private split below; do not
   duplicate variables between inventory and Vault.
   SMTP must support STARTTLS or implicit TLS. The deployment account has Docker
   and sudo authority and is therefore a host administrator; protect its key.
5. Bootstrap once, from the configured controller with initial SSH access:

   ```sh
   export ANSIBLE_CONFIG="$PWD/deploy/ansible/ansible.cfg"
   ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/bootstrap.yml \
     -e @deploy/ansible/inventory/production.vault.yml --ask-vault-pass \
     -e ansible_host=INITIAL_HOST -e ansible_user=INITIAL_ADMIN --ask-become-pass
   ```

   Bootstrap installs `gpg` before configuring signed vendor package repositories
   (required by Ansible's `apt_repository` module on minimal Debian installations).
   It uses Tailscale's standard `tailscale.list` and
   `/usr/share/keyrings/tailscale-archive-keyring.gpg` paths so an existing official
   installation can be reused. Before any APT operation, it removes the obsolete
   bootstrap entry from `pkgs_tailscale_com_stable_debian.list`, backing up that
   file and preserving other entries. This also repairs a previous failed run
   that left conflicting `Signed-By` paths. See the
   [official Tailscale Debian instructions](https://pkgs.tailscale.com/stable/#debian-trixie).
   Bootstrap installs signed vendor Docker/Tailscale packages, distribution msmtp,
   and uv 0.10.9. It installs age and rclone when backups are enabled. It generates
   the PostgreSQL password once and preserves it on reruns. It creates private directories, installs runtime
   secrets and timers, enrolls Tailscale and persists Serve. No application images
   are built on the host. Check the resulting Tailscale DNS name matches inventory;
   restrict initial public SSH in the provider/host firewall after tailnet SSH works.
6. Create GitHub environment `private`. Set secrets `DEPLOY_SSH_KEY`,
   `DEPLOY_KNOWN_HOSTS`, `TS_OAUTH_CLIENT_ID`, and `TS_AUDIENCE`. Configure Tailscale
   workload identity federation for this repository's `private` environment,
   issuer `https://token.actions.githubusercontent.com`, subject
   `repo:OWNER/REPO:environment:private`, the configured audience, `auth_keys` scope
   and `tag:polybot-ci`. Use ordinary OpenSSH, not Tailscale SSH. Permit Actions
   package and release publication using `GITHUB_TOKEN`; grant this repository
   Actions read access to its GHCR packages. Enable failure notifications for
   the named operator. Do not configure required environment approval if unattended
   tagged deployment is intended. Protect the default branch and version tags.
7. Push the first version tag, then run Ansible `status.yml`; also run `backup.yml`
   when backups are enabled.
   Timers intentionally wait for a first active release. Complete the external
   acceptance checklist below before declaring operational setup complete.

The examples contain placeholders; operators supply production inventory values
and encrypted credentials. Tailscale currently advertises 1,000 ephemeral-resource minutes
per month on Personal. CI joins only in remote-operation jobs; connectivity runs
once daily with a five-minute job bound. Track usage and pause automation if the
free allowance is exhausted; reassess changed terms without enabling paid capacity.
[Tailscale pricing](https://tailscale.com/pricing) and
[workload identity GitHub integration](https://tailscale.com/docs/integrations/github/github-action)
were checked for this implementation.

## Public inventory and private credentials

Commit both files under `deploy/ansible/inventory/`:

- `production.yml`: non-secret configuration in plain YAML.
- `production.vault.yml`: secrets encrypted with Ansible Vault.

Keep the Vault password in a password manager outside Git. If a future CI job needs
to decrypt the file, supply that password through a CI secret. The existing release
workflow does not need it; bootstrap installs the runtime secrets on the host.

For a new setup, run from the repository root (do not overwrite an existing Vault):

```sh
ansible-vault encrypt deploy/ansible/inventory/secrets.example.yml \
  --output deploy/ansible/inventory/production.vault.yml
ansible-vault edit deploy/ansible/inventory/production.vault.yml
```

The first command encrypts a copy of the placeholder template and asks you to choose
a Vault password. The second opens the encrypted copy so you can fill in the real
values; it saves the file encrypted again. Use that same `ansible-vault edit` command
for later changes. Do not use `ansible-vault decrypt` on the tracked file.

If you already filled in a plaintext secrets file, encrypt that file instead of
the template, using `--output deploy/ansible/inventory/production.vault.yml`. The
original plaintext file remains on disk; remove it after verifying the encrypted
copy with `ansible-vault edit`, and never stage it. An existing encrypted file can
be moved to `production.vault.yml` without decrypting it.

Before staging, check that `production.vault.yml` starts with `$ANSIBLE_VAULT;` and
contains ciphertext, then stage only the intended files:

```sh
git add deploy/ansible/inventory/production.yml \
  deploy/ansible/inventory/production.vault.yml
```

| Value | Location |
| --- | --- |
| `polybot_ssh_public_key` (entire deployment `.pub` file) | Public inventory, under `vars` |
| `polybot_smtp_username` (mailbox login, usually its full email address) | Public inventory, under `vars` |
| `polybot_sftp_known_hosts` (verified storage host public key records; backups only) | Public inventory, under `vars` |
| `polybot_age_recipients` (public encryption recipients; backups only) | Public inventory, under `vars` |
| `polybot_tailscale_authkey` | Encrypted `production.vault.yml` |
| `polybot_smtp_password` | Encrypted `production.vault.yml` |
| `polybot_sftp_private_key` (backups only) | Encrypted `production.vault.yml` |

The deployment SSH **private** key stays on the controller and is supplied to CI
through `DEPLOY_SSH_KEY`; it does not belong in either inventory example. The age
private recovery identity stays offline. The controller's `known_hosts` file
contains public host keys, not secrets; verify those keys through a trusted channel.

When updating an existing setup, move the four non-secret variables above from
Vault to the inventory's `vars` section (backup values only when enabled), then
remove their Vault definitions. Ansible uses the same variable names regardless
of which file supplies them. Use the `-e @deploy/ansible/inventory/production.vault.yml`
argument shown in the bootstrap command above to load the encrypted file.

## Optional SFTP backups

Set `polybot_backups_enabled: false` in your production inventory to opt out.
Omit `polybot_sftp_host`, `polybot_sftp_port`, `polybot_sftp_user`,
`polybot_sftp_directory`, `polybot_sftp_private_key`, `polybot_sftp_known_hosts`,
and `polybot_age_recipients`. Other deployment inputs remain required. For
compatibility, inventories that omit the flag keep backups **enabled** and must
supply the complete backup configuration. Use a YAML boolean, not a quoted string.

With backups disabled, bootstrap stops and disables both backup timers and stops
any running backup/check services. Application, private HTTPS, and host monitoring
continue; status reports `"backups_enabled": false` and excludes remote freshness
and backup-unit checks. Explicit `backup.yml` or host backup/check commands fail
with a disabled message. No scheduled snapshots or remote retention run, and the
24-hour recovery-point objective is unavailable. This mode provides no automatic
local-backup fallback. Retained staging files, backup credentials and remote
archives are preserved; manage their expiry separately while backups are disabled.

To enable later, set the flag to `true`, provide all SFTP fields and backup secrets,
install age on the controller, and rerun bootstrap with the encrypted secrets.
Run `backup.yml` and verify an offline-identity restore before claiming recovery
coverage. To change an existing host, first deploy a release containing support
for this flag, then rerun bootstrap; older installed operational bundles cannot
read the new configuration. Disabling requires the same bootstrap rerun.

## Routine releases

Commit and merge to the default branch, then:

```sh
git tag v1.0.0
git push origin v1.0.0
```

Use the next unused `vMAJOR.MINOR.PATCH`. Required reusable workflows run backend,
frontend, browser and deployment acceptance before image publication. Docker's
login, QEMU, Buildx and build/push actions select the inventory architecture,
use GitHub cache and publish with `GITHUB_TOKEN`. Reviewed infrastructure pins
live in `deploy/infrastructure.env`; application releases never resolve new
PostgreSQL/Redis digests. A change to these pins needs a separate maintenance plan.

The single GitHub Release asset `release.tar.gz` contains `bundle.json`,
`images.env`, the exact Compose file and committed operational source/lockfiles.
It contains no credentials. Metadata binds tag, commit and all included file
hashes. The selected commit must be in default-branch history. Existing complete
assets are downloaded and verified on retry; moved tags, drafts, missing or extra
assets and checksum/provenance conflicts fail instead of being overwritten. A
partial draft needs operator inspection and removal or completion before retry;
never replace a published release. Image-only publication failures can rebuild
before there is a completed bundle. A completed bundle is reused without builds.

For a published release, open **Actions → Private release → Run workflow**, enter
`release_tag`, and choose `deploy` or `rollback`. Manual operations never build an
unpublished release. Rollback checks schema compatibility; it never downgrades the
database. The workflow serializes releases without cancelling an active one and
reports commit, digests, result and the diagnostic journal location.

Ansible is also the private operator interface:

```sh
ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/status.yml
# When backups are enabled:
ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/backup.yml
```

For exceptional local deploy/rollback, download the published bundle with
`gh release download TAG --pattern release.tar.gz --dir /secure/release`, then
invoke `deploy.yml` or `rollback.yml` with private extra vars containing
`release_tag`, `release_commit`, absolute `release_bundle`, `registry_username`
and a short-lived `registry_token`. Do not put credentials on command lines.
The workflow supplies these automatically for routine releases.

## Release and rollback

All installed state uses one configured root:

```text
/srv/polybot/                 private, owned by polybot
  runtime.env                bootstrap origin/SMTP/path settings, mode 600
  secrets/                   private directory; container secrets readable by UID 10001
  operations.json            backup enablement, optional SFTP destination, origin, port and alerts
  bundles/TAG/               verified source, release.tar.gz and locked .venv
  releases/ATTEMPT/           durable candidate and previous Compose/manifests
  .deployment.json           pending attempt phase and operation
  .env, docker-compose.yml   active configuration
  current -> bundles/TAG     operational source selected during promotion
  staging/                   encrypted backup staging; at most two failed snapshots
```

Ansible validates/transfers the bundle and installs its locked Python environment
before touching application processes. `polybot-activate.service` then invokes
`scripts.beta_release --bundle ... --app-dir ...` under systemd. SSH loss does not
kill activation. A rerun waits for the existing unit and reads its journal before
launching another attempt. Temporary Docker authentication is removed by
`ExecStopPost`, including activation failure or disconnect. Host locking protects
manual executor invocations and backup snapshots too.

The single executor validates inputs, pulls images, preserves existing
PostgreSQL/Redis containers, stops ingress, stops applications, runs forward
migration (or rollback compatibility check), starts `api`, `worker` and `recovery`, waits for
readiness, and promotes configuration. Failed migrations/rollback checks leave
ingress closed. Reapplying the active healthy bundle checks health without
restarting paper runs. An unhealthy active bundle reports failure; repair the
service or deploy a reviewed repair, rather than assuming rollback is safe.

The durable ACTIVATING journal replays the retained candidate. ACTIVATED recovers
partial `.env`, Compose or `current` promotion without restarting applications.
An uncertain activation with no durable completion record is replayed. Retrying
the same pending candidate requires its recorded deploy/rollback operation. An
explicit different bundle can replace a failed attempt with a forward repair or
schema-compatible rollback. Never edit/delete the journal to bypass recovery.
Diagnostics: `journalctl -u polybot-activate.service`; active inputs can be mixed
until recovery finishes, so recover before manual Compose operations. Keep volumes;
never run `down --volumes` on retained data. Paper runs interrupted by a real
release require explicit relaunch; existing recovery fences remain in effect.

## Private HTTPS boundary

Serve persists `tailscale serve --bg --https=443 http://127.0.0.1:8081`, with the
configured internal port substituted. Tailscale owns certificates and renewal;
no production TLS files are mounted into Caddy. Serve rejects internet ingress
unless Funnel is separately enabled, which bootstrap and host checks reject.
[Serve persistence](https://tailscale.com/docs/reference/tailscale-cli/serve).

`POLYBOT_AUTH_ORIGIN` is the exact external HTTPS origin;
`POLYBOT_HTTP_PORT` is an independent loopback listener, default 8081. Caddy keeps
static frontend serving, API proxying and immediate SSE flushing. Uvicorn trusts
only Caddy `172.30.16.2`; Caddy trusts only Docker host gateway `172.30.16.1/32`,
uses strict right-to-left X-Forwarded-For parsing and sends a single client IP.
The subnet `172.30.16.0/28` must be free on the host. Other containers are untrusted.
Serve overwrites X-Forwarded-For with the authenticated connection's source IP;
Caddy removes `Forwarded` and Tailscale identity headers and fixes the upstream
scheme to HTTPS. Application login remains required, Secure cookies and CSRF
use the configured origin, and mail links retain that origin.
[Tailscale forwarding implementation](https://github.com/tailscale/tailscale/blob/v1.94.2/ipn/ipnlocal/serve.go),
[Caddy trusted proxies](https://caddyserver.com/docs/caddyfile/options#trusted-proxies).

## Acceptance and removal inventory

Ordinary disposable checks, from the root (Docker, age, rclone, OpenSSH tools,
Ansible and Chromium required; on macOS install Caddy for the local TLS fixture):

```sh
uv run pytest backend/tests/control_plane/test_beta_host_deployment.py backend/tests/control_plane/test_release_automation.py backend/tests/control_plane/test_remote_backups.py backend/tests/control_plane/test_host_monitoring.py
PYTHONPATH=backend/tests uv run python -m control_plane.deployment_smoke
PYTHONPATH=backend/tests uv run python -m control_plane.backup_rehearsal
PYTHONPATH=backend/tests uv run python -m control_plane.bootstrap_rehearsal
```

The HTTPS rehearsal uses a separate disposable TLS terminator in front of the
production Caddy HTTP path. Its local certificate is test-only. It covers login,
secure cookies, origin/CSRF, forwarding spoof resistance, email origin, browser
run/Stop/reload, SSE reconnect, dependency loss and schema failure. Bootstrap
acceptance runs Debian systemd in a disposable privileged container; it skips only
external tailnet enrollment/Serve. It must preserve credentials with zero changes
on its second preparation pass, preserve a running container and volume, and
prove a detached systemd operation survives SSH client loss. Backup acceptance restores downloaded SFTP bytes
into a new quarantined Compose project and compares account/ownership/history.
No retained host or external account is changed by these commands.
Recorded repository results and the limits of these fixtures are in
[deployment validation](deployment-validation.md).

External acceptance remains required on a disposable target in the actual tailnet:
verify the exact private Serve path from an allowed client, login and Secure
cookies, rejected foreign-origin mutations, spoofed forwarding headers, real
client addresses/rate limits, HTTPS mail links, SSE reconnect, and no unauthenticated
application access. Reboot and repeat Serve checks. Verify CI ephemeral cleanup,
SSH/HTTPS-only policy, GHCR permissions, release publication/reuse, SSH loss during
activation, real SMTP failure/recovery delivery, daily GitHub unreachable-host
notifications and, when backups are enabled, actual SFTP host keys and an
offline-identity restore. Record the backup mode, date,
commit, host architecture and outcomes before declaring setup complete. Missing
account/host inputs are activation blockers, not passing acceptance evidence.

Removed: `beta_publish`, `beta_setup`, `beta_start`, `ghcr`, deployment `buildx`,
`source`, and `tls` helpers; the local-only recovery-point predicate,
fixed-path mounted-backup units and their obsolete
tests. Their laptop builds, SCP transfers, host Git fetches, interactive registry
logins, certificate copying/renewal and backup mounts disappear. The remaining
release executor, durable journal, Compose/private-file helpers and encrypted
backup/isolated restore logic retain application-specific safety responsibilities.

The deployment style-review follow-up adds regression coverage at the installed
boundaries. `uv sync --extra dev` includes the pinned Ansible controller used by
these tests. Run the focused contracts with:

```sh
uv run pytest backend/tests/control_plane/test_deployment_boundaries.py backend/tests/control_plane/test_deployment_contracts.py backend/tests/control_plane/test_backup_boundaries.py backend/tests/control_plane/test_beta_host_deployment.py backend/tests/control_plane/test_remote_backups.py backend/tests/control_plane/test_host_monitoring.py
PYTHONPATH=backend/tests uv run python -m control_plane.bootstrap_rehearsal
PYTHONPATH=backend/tests uv run python -m control_plane.backup_rehearsal
```

The Debian rehearsal executes Ansible staging, the installed executor, systemd
and real disposable Compose processes, including deploy, rollback, retained-bundle
conflicts, failures, retries, and private HTTPS readiness failure. It substitutes
local TLS for the unavailable target tailnet and fixture registry authentication;
the separate application/backup rehearsal uses the real application images and
PostgreSQL. Mail acceptance uses the rendered msmtp configuration, authenticated
STARTTLS and the host alert transition path. These remain disposable acceptance
fixtures; production tailnet, registry, storage and SMTP acceptance still requires
the reviewed operator inventory and credentials.

Extraction runs as the service account so archive-created parent directories are
writable during locked environment installation. The controller validates the
retained database password before rendering dependent secrets. Inventory, exact
release identity, Tailscale status/Serve, Compose status, artifact metadata and
alert state are validated at their ingress boundaries before host mutations.

Bootstrap's controller requires OpenSSH `ssh-keygen` locally, plus `age` when
backups are enabled. Before host mutation it validates deployment public keys,
SMTP credentials, and a Tailscale enrollment key (unless the tailnet stage is
explicitly skipped). Enabled backups additionally require validated non-interactive
SFTP private keys, a known-host entry matching the configured storage host/port,
and age recipients. It exports normalized inventory values to Ansible; ports must
be YAML integers. Remote access is still verified by the separate
connectivity/backup acceptance checks.

Tailscale enrollment accepts only the states defined by the pinned [official v1.94.2 backend](https://github.com/tailscale/tailscale/blob/v1.94.2/ipn/backend.go); unknown states fail before enrollment. Host status and activation validate the `current` pointer against the installed bundle and its runtime image identity.
