# Private deployment and release operations

Use GitHub Actions, Ansible and Docker Compose on one Debian host, amd64 or
arm64. Tailscale Personal supplies private connectivity and Serve HTTPS. The API
keeps its own email/password authentication. The application remains paper-only;
no public-opening gate or live-trading opt-in is changed.

## One-time setup

Run steps 1–5 before configuring GitHub releases. Account creation and credentials
are operator inputs; no automation buys capacity, upgrades a plan or enables
Funnel. Commands marked **on your Mac/controller** run from the repository root.
Commands marked **on the server** run through its console or an SSH session.
The controller is the computer running Ansible; it is not the deployment server.

Examples use the existing administrator `hec`, the server name `hec-server`, and
`hec-server.tailnet-name.ts.net`. Replace the tailnet hostname with the exact name
shown for your machine in Tailscale. Replace `accounts@example.com` with your real
mailbox. Example keys and passwords are placeholders, not usable credentials.

Jump to [server preparation](#1-prepare-the-debian-server-and-existing-administrator),
[Tailscale](#2-configure-tailscale-the-hostname-and-private-https),
[controller and keys](#3-prepare-your-maccontroller-and-deployment-ssh-key),
[inventory and Vault](#4-fill-the-public-inventory-trust-file-and-encrypted-vault),
[bootstrap](#5-bootstrap-with-the-existing-administrator), or
[GitHub releases](#6-configure-github-releases).

| Identity or file | Purpose |
| --- | --- |
| Existing server administrator, such as `hec` | First SSH connection and sudo during preparation/bootstrap |
| Server account `polybot` | Created by bootstrap for subsequent deployments |
| Administrator's SSH key | Lets your Mac connect as `hec` before bootstrap |
| Deployment SSH key pair | Later lets your Mac and CI connect as `polybot` |
| Server SSH host public key in `known_hosts` | Lets clients verify that they reached the correct server |
| Tailscale auth key | Enrolls the server in the private network; separate from SSH authentication |
| SMTP app password | Lets the application send email through your mailbox provider |
| Ansible Vault password | Decrypts the secrets file on the controller |

### 1. Prepare the Debian server and existing administrator

**Why:** Ansible needs a reachable OpenSSH server and an account that can obtain
root privileges. Remote Python and sudo can be installed by bootstrap itself.
Use Debian 12/13, amd64 or arm64. The staging baseline is four CPUs, 8 GiB RAM and
40 GiB free disk; repeat capacity acceptance on the actual host.

There is no preparation script to copy or run, and no server checkout or Ansible
installation is required. Set the final machine hostname before Tailscale enrollment.
Verify the server's SSH host key through the console/provider before connecting.
From your Mac, install your administrator's public key if needed and test it
(replace `INITIAL_HOST` with the reachable LAN/public address):

```sh
ssh-copy-id -i ~/.ssh/id_ed25519.pub hec@INITIAL_HOST
ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes \
  -o ControlMaster=no -o ControlPath=none -o PreferredAuthentications=publickey \
  -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  hec@INITIAL_HOST 'id -un'
```

Expect `hec`. Choose an existing privilege path for step 5:

| Initial access | Bootstrap invocation |
| --- | --- |
| `hec` can run sudo | Connect as `hec`, use `--ask-become-pass` with hec's password |
| `hec` can use `su` but sudo is missing/unavailable | Connect as `hec`, use `--become-method=su --ask-become-pass` with the root password |
| Existing root SSH access | Connect as `root`; no become password is needed |

If none works, use the server console/provider to establish an SSH account and
root access first; automation cannot grant itself privileges. You do not need
to enable root SSH when sudo or su already works. Keep an existing session open
through the first bootstrap. Ansible creates `polybot`, installs its deployment
key, and proves fresh SSH plus passwordless sudo before hardening SSH at the end.
If you want to retain `hec` as a human sudo administrator, set
`polybot_admin_user: hec`; the account must already exist. New group membership
takes effect in a fresh login. Lid behavior, swap and security packages are now
Ansible-managed settings in step 4.

### 2. Configure Tailscale, the hostname and private HTTPS

**Why:** Tailscale connects the controller, deployment server and CI privately.
Serve provides the application's HTTPS address and certificate. The domain you
bought for email does not automatically become the application's address.

1. Use the intended Tailscale **Personal** tailnet and connect your Mac to it.
   With initial LAN/public SSH, leave server installation/enrollment to Ansible.
2. Open the [Tailscale admin console](https://login.tailscale.com/admin/). Under
   **Machines**, confirm an existing server's machine name and full DNS name.
   For a fresh server, use its final hostname and your tailnet's DNS suffix to
   select the intended origin; bootstrap verifies the enrolled DNS name exactly.
3. Under **DNS**, enable **MagicDNS** and **HTTPS Certificates**. Use the full
   `https://HOST.TAILNET.ts.net` address, including `https://`, as the origin.
   See [Tailscale HTTPS setup](https://tailscale.com/docs/how-to/set-up-https-certificates).
4. Merge [`deploy/tailscale-policy.example.hujson`](../deploy/tailscale-policy.example.hujson)
   into the tailnet access policy. It defines `tag:polybot` and `tag:polybot-ci`.
   Remove broader grants that would give CI more than TCP 22 and 443 to the server.
   Retain a scoped TCP 22 grant for your administrator identity if using tailnet
   SSH from your Mac: the example's member grant permits HTTPS only. For example,
   an additional grant can use `"src": ["you@example.com"]`,
   `"dst": ["tag:polybot"]`, and `"ip": ["tcp:22"]`, with your actual login identity.
5. The tagged auth-key flow applies `tag:polybot` during Ansible enrollment. For an
   already-enrolled server, apply it in the admin console if absent; bootstrap
   retains an already-running enrollment.
   CI will use `tag:polybot-ci`; do not apply the CI tag to the server.

Keep **Funnel disabled**. The application is intended to be reachable through
Tailscale, with its own email/password login. Ordinary OpenSSH travels over
Tailscale; this setup does not use Tailscale SSH.

**Tailscale is the only route to the server?** That connection must exist before
Ansible can use it. From the server console, install Tailscale using the
[official Debian instructions](https://pkgs.tailscale.com/stable/), then run
`tailscale up --ssh=false` as root. Open its browser URL on your Mac, sign in as
**attosoria@hotmail.com**, complete device approval and apply the host tag above.
This is the only route-dependent manual installation; Ansible manages the rest.
Browser enrollment is also available if you prefer it over first enrollment with
an auth key. Keep ordinary OpenSSH enabled and verify it works over Tailscale.

#### Get `polybot_tailscale_authkey`

In the admin console, open **Settings → Keys → Generate auth key** and select:

| Setting | Value and reason |
| --- | --- |
| Description | `polybot-server-bootstrap`, so you can identify its purpose |
| Reusable | Off: enroll one server |
| Ephemeral | Off: this server should remain in your tailnet |
| Tags | `tag:polybot`, defined in the policy above |
| Pre-approved | Enable if your tailnet uses device approval |
| Expiration | Choose a period that covers your planned bootstrap |

Copy the generated `tskey-auth-...` value into `polybot_tailscale_authkey` in Vault
in step 4. This is an **auth key**, not an API key or CI OAuth credential.
[Tailscale auth-key documentation](https://tailscale.com/docs/features/access-control/auth-keys).

**Already connected?** Bootstrap will skip the enrollment command while Tailscale
is running, but its current input validator still requires a `tskey-auth-...`
value for the normal bootstrap invocation. Keep it in Vault even in that case.
The validator checks the prefix; it does not prove the key is unused or unexpired.
A one-time key is consumed on enrollment; generate a new one if the server later
needs re-enrollment. Do not skip the whole tailnet stage merely to avoid supplying
this value, because that stage also validates/configures private HTTPS Serve.

### 3. Prepare your Mac/controller and deployment SSH key

**On your Mac/controller**, from the repository root, with `uv` and OpenSSH
(`ssh`, `ssh-keygen`) installed:

```sh
uv sync --locked --extra dev
uv tool install ansible-core==2.19.7
ansible-playbook --version
command -v ssh-keygen
```

#### Generate a dedicated deployment key

Do this once, choosing a different filename if the following files already exist:

```sh
ssh-keygen -t ed25519 -C "polybot-deployment" -f ~/.ssh/polybot_deploy -N ""
cat ~/.ssh/polybot_deploy.pub
```

Copy the entire public line (`ssh-ed25519`, key data, and optional comment) into
`polybot_ssh_public_key` in the public inventory. This example uses no passphrase
because the current unattended CI workflow loads the private key directly.
Protect the private file; the resulting server account has Docker and unrestricted
sudo authority and is therefore a host administrator.

| Generated file | Where it goes |
| --- | --- |
| `~/.ssh/polybot_deploy.pub` | Contents go into public `production.yml`; bootstrap installs them in `/home/polybot/.ssh/authorized_keys` |
| `~/.ssh/polybot_deploy` | Stays private on your Mac; later its full contents become GitHub's `DEPLOY_SSH_KEY` secret |

Do **not** add the deployment key to the server manually. The first bootstrap uses
your existing administrator's working SSH key; then Ansible installs the new
public key for `polybot`. These are different from the server host key used below.
An existing deployment key pair also works if you deliberately choose to reuse it.

#### Optional backups

The example uses `polybot_backups_enabled: false`. You can proceed without SFTP
storage, backup keys, `age` on the controller, or an age recovery identity.

If enabling backups, set it to `true`, install `age` on the controller, and obtain
an SFTP host, port, user and a dedicated existing directory with read/write/delete
permissions. Verify its SSH host public key through a trusted channel. Generate a
separate non-interactive SFTP key pair and arrange storage-side authorization.
On the protected recovery machine, generate the encryption identity:

```sh
age-keygen -o recovery.age
age-keygen -y recovery.age
```

Only the public `age1...` output goes into `polybot_age_recipients` in inventory.
Keep `recovery.age`, the private decryption identity, offline and outside the
server and SFTP storage. Put the SFTP private key in Vault. See
[optional SFTP backups](#optional-sftp-backups) for enabling and verifying recovery.

### 4. Fill the public inventory, trust file and encrypted Vault

There are three repository files to maintain:

```text
known_hosts                                      # Verified server public keys
deploy/ansible/inventory/production.yml          # Public configuration
deploy/ansible/inventory/production.vault.yml    # Encrypted secrets
```

#### Fill `production.yml`

Copy the example **on your Mac/controller**, only if you have not created it yet:

```sh
cp deploy/ansible/inventory/production.example.yml deploy/ansible/inventory/production.yml
```

A Namecheap Private Email setup with backups disabled looks like this. Replace
all example values with your own, including the full deployment public key:

```yaml
all:
  children:
    polybot:
      hosts:
        beta:
          ansible_host: hec-server.tailnet-name.ts.net
          ansible_user: polybot
          ansible_ssh_common_args: '-o UserKnownHostsFile=./known_hosts -o StrictHostKeyChecking=yes'
      vars:
        polybot_ssh_public_key: 'ssh-ed25519 REPLACE_WITH_FULL_PUBLIC_KEY polybot-deployment'
        polybot_root: /srv/polybot
        polybot_arch: amd64
        polybot_origin: https://hec-server.tailnet-name.ts.net
        polybot_http_port: 8081
        polybot_admin_user: hec
        polybot_ignore_lid: true # This example is a headless laptop
        polybot_manage_swap: true
        polybot_swap_size_mib: 2048
        polybot_swappiness: 10
        polybot_smtp_host: mail.privateemail.com
        polybot_smtp_port: 587
        polybot_smtp_security: starttls
        polybot_smtp_from: accounts@example.com
        polybot_smtp_username: accounts@example.com
        polybot_alert_to: operator@example.com
        polybot_backups_enabled: false
```

| Setting | How to choose it |
| --- | --- |
| `beta` | Ansible's local alias for this server; it need not match its DNS name |
| `ansible_host` | Target server's SSH hostname or address, without `https://`; normally its full Tailscale name |
| `ansible_user` | Keep `polybot` for routine deployments; override with your existing administrator during the first bootstrap |
| `polybot_ssh_public_key` | Entire deployment client `.pub` line from step 3, not the server's host key |
| `polybot_root` | Dedicated application directory on the server; default `/srv/polybot` |
| `polybot_arch` | Run `uname -m` on the server: `x86_64` means `amd64`, `aarch64` means `arm64` |
| `polybot_origin` | Exact browser origin, including `https://`; use the server's full Tailscale DNS name without a path or trailing slash |
| `polybot_http_port` | Local application listener behind Serve; keep `8081` unless changing the port deliberately; it is not the SSH or external HTTPS port |
| `polybot_smtp_host` | Outgoing mail server provided by your email provider, such as `mail.privateemail.com` |
| `polybot_smtp_port` / `polybot_smtp_security` | Namecheap example: `587` with `starttls`; implicit TLS uses `465` with `tls` |
| `polybot_smtp_from` | Sender email address; using the authenticated mailbox is the simplest setup |
| `polybot_smtp_username` | Full mailbox login address for Namecheap Private Email, not your Namecheap account username |
| `polybot_alert_to` | Your operator mailbox for host alerts |
| `polybot_backups_enabled` | YAML boolean `false` or `true`, without quotes; optional backup fields are required when true |
| `polybot_admin_user` | Optional existing non-root account to add to the sudo group; omitted by default; `polybot` is always created separately |
| `polybot_ignore_lid` | Default `false`; use `true` for a headless laptop. Returning to false removes the managed logind override |
| `polybot_manage_swap` | Default `true`; `false` leaves existing swap, fstab and swappiness untouched for manual management |
| `polybot_swap_size_mib` | Default `2048`, minimum `128`; an existing `/swapfile` must match the selected size and have a swap signature; never resized automatically |
| `polybot_swappiness` | Default `10`, allowed `0`–`100`; applied and persisted when swap management is enabled |

Swap management supports ext2/3/4 and XFS and needs the requested size plus
512 MiB free for a new file. For Btrfs or another unsupported filesystem, configure
swap separately and set `polybot_manage_swap: false`. Symlinks, hard links,
conflicting fstab entries and unexpected existing files stop bootstrap rather than
being overwritten. An interrupted allocation without a swap signature needs manual
inspection. Active swap still gets its persistence checked and repaired.

**Already ran the retired preparation script?** Ansible reuses its swapfile and
managed drop-ins. Set `polybot_ignore_lid: true` explicitly to retain headless
laptop behavior; the default false removes that override. Keep the desired swap
size consistent with the existing file. No manual file removal is needed to
switch to Ansible ownership, and a running Tailscale enrollment is retained.

`ansible_host` and `polybot_origin` refer to the same deployment server, but one is
an SSH destination and the other is its browser URL. Buying `example.com` does
not change that URL: using `https://app.example.com` would require a different
routing and HTTPS setup. Your purchased domain can still supply the email address
`accounts@example.com` while the application uses Tailscale HTTPS.

Namecheap's `privateemail._domainkey` is a **DKIM DNS record name**, used to verify
email signatures. It is not an SMTP hostname and does not belong in
`polybot_smtp_host`. Configure provider-required DNS authentication records in the
domain's DNS panel. An actual Private Email mailbox is required; owning a domain
alone does not provide SMTP credentials. See
[Namecheap SMTP settings](https://www.namecheap.com/support/knowledgebase/article.aspx/1179/2175/general-private-email-configuration-for-mail-clients-and-mobile-devices/)
and [DKIM setup](https://www.namecheap.com/support/knowledgebase/article.aspx/10383/2176/how-to-set-up-a-dkim-record-for-private-email/).

#### Create the repository's `known_hosts`

**Why:** Your client must verify the server's identity before sending credentials.
The inventory explicitly sets `UserKnownHostsFile=./known_hosts`, so a valid entry
in `~/.ssh/known_hosts` alone will not satisfy this configuration.

Through the server console/provider channel or an already trusted SSH connection,
run **on the server**:

```sh
cat /etc/ssh/ssh_host_ed25519_key.pub
```

It returns `ssh-ed25519`, the server's public key data, and perhaps a comment such
as `root@hec-server`. Create `known_hosts` **at the repository root on your Mac**
and add the full hostname before that public-key record:

```text
hec-server.tailnet-name.ts.net ssh-ed25519 REPLACE_WITH_FULL_SERVER_HOST_PUBLIC_KEY root@hec-server
```

The trailing comment is optional. A line for `hec-server` alone does not cover
`hec-server.tailnet-name.ts.net`; add the exact address you will use. If the first
bootstrap connects via an initial IP/LAN address, add a verified entry for that
address too. Both entries can contain the same server public key. For a custom
SSH port, use `[HOST]:PORT` in `known_hosts` and configure `ansible_port` accordingly.

If you already verified and saved the exact hostname in `~/.ssh/known_hosts`, you
can copy that entry into the repository file. Find it with:

```sh
ssh-keygen -F hec-server.tailnet-name.ts.net -f ~/.ssh/known_hosts
```

Do not treat an unauthenticated `ssh-keyscan` result as proof of identity. Keep
strict checking enabled. Commit the repository `known_hosts`: its keys are public.
If the host is reinstalled or its identity key rotates, verify the replacement
through the console before changing this file.

Check lookup and a fresh administrator connection **from the repository root**:

```sh
ssh-keygen -F INITIAL_HOST -f ./known_hosts
ssh -o UserKnownHostsFile=./known_hosts -o StrictHostKeyChecking=yes \
  -o ControlMaster=no -o ControlPath=none -o BatchMode=yes \
  hec@INITIAL_HOST 'id -un'
```

The SSH command should print `hec`. If your administrator key has a non-default
filename, add `-i ~/.ssh/YOUR_ADMIN_KEY`; use the matching `--private-key` option
when invoking Ansible in step 5.

#### Public inventory and private credentials

Public keys are not secrets. They belong in plain YAML even though they are used
for authentication or encryption. Keep one definition of each variable:

| Value | Location |
| --- | --- |
| `polybot_ssh_public_key` | Public `production.yml`, under `vars` |
| `polybot_smtp_username` | Public `production.yml`, under `vars` |
| `polybot_sftp_known_hosts` (verified storage host public keys; backups only) | Public `production.yml`, under `vars` |
| `polybot_age_recipients` (public encryption recipients; backups only) | Public `production.yml`, under `vars` |
| `polybot_tailscale_authkey` | Encrypted `production.vault.yml` |
| `polybot_smtp_password` | Encrypted `production.vault.yml` |
| `polybot_sftp_private_key` (backups only) | Encrypted `production.vault.yml` |
| Deployment SSH private key | Private file on controller; later GitHub secret `DEPLOY_SSH_KEY` |
| Age private recovery identity | Offline recovery custody |
| Vault password | Password manager outside Git |

If using an older secrets file, move the four public variables above into
inventory's `vars` section and remove their Vault definitions. Ansible reads the
same variable names from either location; duplicated Vault extra-vars can override
an inventory value you thought you had changed.

#### Obtain `polybot_smtp_password`

For the current Namecheap Private Email platform:

1. Sign into [Private Email webmail](https://privateemail.com/) as the mailbox you
   selected for `polybot_smtp_username`.
2. Open **Settings → Launch Security Center → App passwords**.
3. Choose **Create new password**, name it `polybot`, and confirm with your mailbox
   password when prompted.
4. Save the generated app password immediately; it is shown only once. Paste it
   exactly, including hyphens, into `polybot_smtp_password` in Vault.

This is not the Namecheap account password. A dedicated SMTP app password also
avoids confusing the mailbox's current webmail password with its email-client
credentials. Legacy mail plans can have different controls; use the provider's
instructions for that mailbox. See
[Namecheap app passwords](https://www.namecheap.com/support/knowledgebase/article.aspx/10816/2178/how-to-use-app-passwords-for-private-email/).

#### Create and edit `production.vault.yml`

**On your Mac/controller**, for a new file only:

```sh
ansible-vault encrypt deploy/ansible/inventory/production.vault.example.yml \
  --output deploy/ansible/inventory/production.vault.yml
chmod 600 deploy/ansible/inventory/production.vault.yml
ansible-vault edit deploy/ansible/inventory/production.vault.yml
```

The first command encrypts a copy of the placeholder template; it does not encrypt
or modify the example itself. Choose a Vault password and save it in your password
manager. The edit command decrypts for editing and saves the file encrypted again.
With backups disabled, the editor should contain these two filled-in secret fields:

```yaml
polybot_tailscale_authkey: 'tskey-auth-REPLACE_WITH_GENERATED_KEY'
polybot_smtp_password: 'REPLACE_WITH_MAILBOX_APP_PASSWORD'
```

Use the same `ansible-vault edit` command for later changes. Do not decrypt the
tracked file in place. Never put the real Vault password in a command, inventory,
or committed password file. The current release workflow does not need the Vault
password: bootstrap installs runtime secrets on the server. If a future CI job
needs decryption, supply the password through a CI secret.

**Existing secrets file?** An already encrypted `secrets.yml` can be renamed to
`production.vault.yml` without decrypting it, provided the destination does not
exist. For an existing plaintext file, use `ansible-vault encrypt PATH_TO_FILE
--output deploy/ansible/inventory/production.vault.yml` instead of encrypting the
example. Verify the encrypted copy with `ansible-vault edit`, then remove the
leftover plaintext file; never stage it. The filename supplied to Ansible must
match the actual file, including its directory.

**Yes, commit the encrypted Vault.** Encryption is what protects its contents;
keeping the ciphertext outside the repository is not required. Git retains old
encrypted versions, so a password change does not re-encrypt past commits. Keep
the Vault password separate from Git and use a strong unique password.

Check that the file starts with `$ANSIBLE_VAULT;` and contains ciphertext. Then
stage the public inventory, encrypted secrets and public host keys explicitly:

```sh
head -n 1 deploy/ansible/inventory/production.vault.yml
git add deploy/ansible/inventory/production.yml \
  deploy/ansible/inventory/production.vault.yml known_hosts
```

### 5. Bootstrap with the existing administrator

**On your Mac/controller**, from the repository root:

```sh
export ANSIBLE_CONFIG="$PWD/deploy/ansible/ansible.cfg"
ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/bootstrap.yml \
  -e @deploy/ansible/inventory/production.vault.yml --ask-vault-pass \
  -e ansible_host=INITIAL_HOST -e ansible_user=INITIAL_ADMIN \
  -e "polybot_ssh_private_key_file=$HOME/.ssh/polybot_deploy" --ask-become-pass
```

| Argument | Meaning |
| --- | --- |
| `ANSIBLE_CONFIG` | Selects this repository's Ansible settings |
| `-i .../production.yml` | Loads the public inventory |
| `-e @.../production.vault.yml` | Loads variables from the encrypted file on your Mac/controller |
| `--ask-vault-pass` | Prompts for the Vault encryption password |
| `-e ansible_host=INITIAL_HOST` | Overrides the normal target address for this connection; use an already reachable IP, LAN name or Tailscale name |
| `-e ansible_user=INITIAL_ADMIN` | Uses the existing account with sudo, su or root access to create/configure `polybot` |
| `polybot_ssh_private_key_file` | Controller-local deployment private-key path used to prove fresh `polybot` access before and after SSH hardening; no key is copied to the server |
| `--ask-become-pass` | Prompts for that existing user's sudo password |

For an already-connected Tailscale server and administrator `hec`:

```sh
export ANSIBLE_CONFIG="$PWD/deploy/ansible/ansible.cfg"
ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/bootstrap.yml \
  -e @deploy/ansible/inventory/production.vault.yml --ask-vault-pass \
  -e ansible_host=hec-server.tailnet-name.ts.net \
  -e ansible_user=hec \
  -e "polybot_ssh_private_key_file=$HOME/.ssh/polybot_deploy" \
  --ask-become-pass
```

If the inventory already has this reachable `ansible_host`, the host override is
optional. The user override is needed for the first bootstrap because `polybot`
does not exist yet. If your current administrator SSH key is not selected by SSH,
add `--private-key ~/.ssh/YOUR_ADMIN_KEY` to this command; use the existing
administrator's key, not the new deployment key unless they are intentionally
identical.

**No sudo yet, but `su` works?** Use the same command with
`--become-method=su --ask-become-pass`; enter the **root password**. Ansible uses
su to install Python/sudo and finish bootstrap. For existing root SSH access,
use `-e ansible_user=root` and omit `--ask-become-pass`. The raw prerequisite task
runs directly as root in that case. Root SSH is disabled only at the final
verified transition; use `polybot` for the next run.

The deployment-key proof is separate from the initial administrator connection.
If `polybot_ssh_private_key_file` is omitted, it uses Ansible's selected private
key, or the SSH agent/default identities when no key file is selected. With
different administrator and deployment keys, pass both `--private-key` for the
administrator and `polybot_ssh_private_key_file` for the deployment account.
Load any encrypted keys into your agent first; verification is non-interactive.
The proof retains the inventory's `ansible_ssh_common_args` and
`ansible_ssh_extra_args` for known-hosts and proxy routing, while forcing a new
key-only connection. Relative key and known-hosts paths resolve from the repository
root, including when Ansible launches the delegated task from `deploy/ansible`.
Custom connection plugins are not supported by this
OpenSSH-based proof. Bootstrap requires a normal run, not `--check`.

The prompts may appear as `BECOME password:` followed by `Vault password:`.
With the sudo method, the first wants **hec's sudo password**; with su it wants
the **root password**. The second wants **your Vault password**.
Neither asks for the SMTP password, Tailscale auth key or deployment private key.

#### What bootstrap does

After inspecting Debian/systemd through SSH and validating public/private inputs
on the controller, bootstrap:

- Repairs its obsolete duplicate Tailscale repository entry before using APT.
  It backs up that source file and preserves unrelated entries. It then installs
  `gpg` before configuring signed repositories, and uses Tailscale's standard
  `tailscale.list` and `/usr/share/keyrings/tailscale-archive-keyring.gpg` paths to
  coexist with an existing official installation. See
  [Tailscale Debian packages](https://pkgs.tailscale.com/stable/#debian-trixie).
- Installs Python and sudo with Ansible's `raw` module when missing, then gathers
  facts. No Python-dependent remote module runs before this prerequisite step.
  See [Ansible raw bootstrap](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/raw_module.html).
- Installs Docker Engine, Compose, Tailscale, msmtp and pinned uv 0.10.9; age/rclone are
  installed when backups are enabled.
- Creates `polybot`, adds it to Docker access, installs the public deployment key
  in `/home/polybot/.ssh/authorized_keys`, and grants passwordless sudo.
- Adds the optional existing human administrator to the sudo group; configures
  optional lid behavior and persistent swap/swappiness according to inventory.
- Enables unattended upgrades and the APT daily timers using the distribution's
  allowed update origins, without adding an automatic-reboot policy.
- Creates the private application directories and runtime configuration, generates
  the PostgreSQL password once, and installs the SMTP/database secrets. Reruns
  preserve the generated database password.
- Retains a running Tailscale enrollment, or enrolls with the tagged auth key when
  needed; validates the expected DNS name and configures persistent private Serve.
- Installs monitoring and optional backup timers, which wait for an active release.
- Proves a fresh `polybot` key login and passwordless sudo, then allows the actual
  SSH listener ports before enabling UFW with deny-incoming/allow-outgoing host
  defaults. Existing UFW rules are retained. Enables and validates an explicit
  fail2ban SSH jail with journald, including on Debian without `auth.log`.
- Finally disables password/keyboard-interactive SSH and root SSH login. It puts
  its policy before existing SSH defaults, validates syntax and effective policy
  globally and for the verified deployment connection, reloads SSH only when
  changed, and proves a new key-only connection again. Failure restores the old
  SSH files and reloads them through the retained original session. An interrupted
  controller or broken original connection can still require console recovery.

There are no new public 80/443 rules: the application uses Tailscale Serve.
UFW does not replace tailnet policy or Docker networking controls; retain the
loopback-only application listener. Custom SSH Match rules or existing firewall
denials may need manual adjustment if the access checks fail. Logind is restarted
only when its managed lid file changes; this may affect desktop sessions.

It does not build application images, deploy a release, or run Alembic migrations.
Successful bootstrap means the host is prepared; the application becomes available
when the first release is activated in step 7. Migrations run during that release
activation, as explained under [database migrations](#database-migrations).

#### Verify deployment access

After successful bootstrap, use your deployment private key **from your Mac**:

```sh
ssh -i ~/.ssh/polybot_deploy -o IdentitiesOnly=yes \
  -o UserKnownHostsFile=./known_hosts -o StrictHostKeyChecking=yes \
  -o ControlMaster=no -o ControlPath=none -o BatchMode=yes \
  polybot@hec-server.tailnet-name.ts.net 'id -un; sudo -n whoami'
```

Expect `polybot` followed by `root`. For later Ansible operations using the
inventory's `ansible_user: polybot`, select this key with
`--private-key ~/.ssh/polybot_deploy` or configure SSH to select it. A custom key
filename is not automatically discovered merely because the file exists.

To reapply bootstrap with the deployment account after the first run:

```sh
ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/bootstrap.yml \
  -e @deploy/ansible/inventory/production.vault.yml --ask-vault-pass \
  --private-key ~/.ssh/polybot_deploy
```

Check `sudo ufw status verbose`, `sudo fail2ban-client status sshd`,
`swapon --show`, and `systemctl list-timers 'apt-daily*'` on the server. Verify
reboot persistence and, for a laptop, SSH reachability with the lid closed;
desktop power managers can also control suspend behavior.

Check the server's Tailscale DNS name matches the inventory and its Serve mapping
is private. Restrict initial public/LAN SSH only after tailnet SSH works. Continue
with GitHub setup and the first release below.

#### Bootstrap troubleshooting

| Symptom | Meaning and next step |
| --- | --- |
| `production.vault.yml` not found; inventory parser also complains about a missing root `plugin` key | First verify the `-e @...` file exists on the controller. Earlier setups named it `secrets.yml`; rename the encrypted file or correct the argument. A static YAML inventory does not need a `plugin` key. If parsing still fails, check YAML indentation separately. |
| `No ED25519 host key is known ... strict checking` | Check `./known_hosts` in the repository root, the exact hostname, and the working directory. `~/.ssh/known_hosts` is a different file. Populate it using the verified server host key; do not disable strict checking. |
| `sudo: not found` at the initial raw tasks | Select an existing privilege path: connect as root, or use `--become-method=su --ask-become-pass` with the root password. Bootstrap can install sudo but cannot invoke missing sudo to get root first. |
| `polybot_admin_user` is undefined after inventory validation succeeds | An earlier playbook stored the normalized dictionary as `_raw_params` instead of installing its facts. Use the corrected `tasks/validate.yml` and rerun from the start. Omitting the optional administrator is supported; the same correction applies all host-policy defaults. |
| Fresh deployment-key SSH proof fails | Supply `polybot_ssh_private_key_file` pointing to the deployment private key, verify its public counterpart in inventory and check `known_hosts`, routing and sudo access. This proof must pass before firewall/SSH hardening. |
| SSH proof reports `Invalid deployment controller input` although direct `polybot` SSH and sudo work | An earlier proof resolved `./known_hosts` from Ansible's playbook directory. Use the corrected `scripts/deployment/ssh_access.py` and rerun the same bootstrap command. Relative paths now resolve from the repository root; SSH failures report a dedicated diagnostic. |
| SSH hardening fails and reports restored configuration | Inspect conflicting `Match` rules or the failed reload/connection check. Keep the original session; use the console if it is unavailable. Correct the conflict and rerun. |
| Bootstrap credentials fail with `no_log: true` and censored output | Check `polybot_ssh_public_key` is a complete parseable client public key, SMTP username/password are present, and the Tailscale value starts with `tskey-auth-`. If backups are enabled, check the SFTP private key, matching verified host record and age recipients too. Inspect Vault locally with `ansible-vault edit`; do not expose secrets by disabling `no_log`. |
| `play_hosts` deprecation warning | This can be triggered when the current playbooks enumerate Ansible variables. It is separate from the later fatal error; use the failed task's message to diagnose the blocker. |
| `Either apt-key or gpg binary is required` | Use the updated bootstrap that installs `gpg` before `apt_repository`. Rerun the full bootstrap. |
| Tailscale repository `Conflicting values ... Signed-By` | An earlier bootstrap added a second source with another key path. The updated bootstrap removes its obsolete entry before the first APT operation and uses the official path. Rerun from the start so that repair runs. |

To check only the public inventory's structure without decrypting secrets or
connecting to the server:

```sh
ansible-inventory -i deploy/ansible/inventory/production.yml --graph
```

Expect `all → polybot → beta`. After fixing an input or dependency, rerun the full
bootstrap command. Completed tasks are designed to be repeatable; starting at a
later task can bypass validation and repair steps.

### 6. Configure GitHub releases

**Why:** GitHub builds and publishes the release, joins your tailnet temporarily,
and connects to the server as `polybot` with the deployment SSH key. Tailscale
workload identity federation lets GitHub prove which repository/environment a
job belongs to without storing a long-lived Tailscale client secret.

Do this **in GitHub and the Tailscale admin console**, using accounts with
repository administration and tailnet administration access. The examples below
use this repository's current identity and default branch:

| Setting | Value for this repository |
| --- | --- |
| Repository | `Hectortilla/Polymarket-bots` |
| Default branch | `master` |
| GitHub environment name | `private` |
| Release tag pattern | `v*.*.*`; actual releases must be `vMAJOR.MINOR.PATCH`, such as `v1.0.0` |
| Tailscale tag for CI runners | `tag:polybot-ci` |
| Tailscale tag already on the server | `tag:polybot` |

If using a fork or renamed repository, substitute its actual owner/name and
default branch throughout. Preserve the repository's spelling in the OIDC subject;
only the container-image namespace below is deliberately lowercased. The name
`private` identifies a deployment environment; it does not change repository,
GitHub Release or package visibility.

#### Create the GitHub environment

1. Open the repository's
   [environment settings](https://github.com/Hectortilla/Polymarket-bots/settings/environments).
   Choose **New environment**, enter `private`, and select **Configure environment**.
   If `private` already exists, open it instead.
2. For unattended deployment, leave **Required reviewers** and **Wait timer** off.
3. Under **Deployment branches and tags**, choose **Selected branches and tags**.
   Add the following two rules using **Add deployment branch or tag rule**:

| Ref type | Name pattern | Why it is needed |
| --- | --- | --- |
| Branch | `master` | Scheduled connectivity checks and manual deploy/rollback runs selected from the default branch |
| Tag | `v*.*.*` | Automatic deployment when a version tag is pushed |

Save both rules. A tags-only environment would block the daily connectivity job.
For manual runs, select `master` in **Use workflow from**, then supply the published
version separately as `release_tag`. These restrictions control access to the
environment; branch/tag protection is configured separately below. See
[GitHub environment setup](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

#### Create the Tailscale federated identity

First confirm the step 2 access policy defines both tags and permits
`tag:polybot-ci` to reach `tag:polybot` on TCP 22 and 443. The server keeps its
`tag:polybot` tag; the temporary GitHub runner receives `tag:polybot-ci`.

In the intended tailnet's admin console, open **Trust credentials**, select
**Credential → OpenID Connect**, and fill in:

| Field | Value to enter or select |
| --- | --- |
| Description, if offered | `polybot-github-private` |
| Issuer | GitHub, if listed; otherwise **Custom issuer** |
| Issuer URL | `https://token.actions.githubusercontent.com` |
| Subject | `repo:Hectortilla/Polymarket-bots:environment:private` |
| Audience, if offered as an optional input | Leave at the generated/default value; copy the resulting **Audience (aud claim)** after creation |
| Scope | **Keys → Auth Keys**, with **Write** access (`auth_keys`) |
| Tags for that scope | `tag:polybot-ci` only |
| Additional custom claims | Leave empty for these existing workflows |

Choose **Generate credential**. Copy its **Client ID** and **Audience (aud claim)**
for the GitHub secrets below. If you deliberately set a custom audience, use that
exact same string in `TS_AUDIENCE`. Do not substitute the application's HTTPS URL
or the issuer URL. The client ID and audience are identifiers visible in Tailscale,
not passwords. See
[Tailscale federated identity setup](https://tailscale.com/docs/features/workload-identity-federation)
and the [action's required scope and tags](https://github.com/tailscale/github-action).

Both [`release.yml`](../.github/workflows/release.yml) and
[`connectivity.yml`](../.github/workflows/connectivity.yml) already request
`id-token: write`, use `environment: private`, and pass these values to Tailscale.
The subject therefore contains `environment:private`, not `ref:refs/heads/master`
or a particular version tag. Keep the complete subject exact; do not use
`repo:Hectortilla/*`.

Despite its name, `TS_OAUTH_CLIENT_ID` takes the **federated identity's Client ID**
in this setup. You do not need an OAuth client secret or another `tskey-auth-...`
server-enrollment key. Ordinary OpenSSH still authenticates the `polybot` login;
keep Tailscale SSH disabled. See the
[Tailscale GitHub Action integration](https://tailscale.com/docs/integrations/github/github-action).

#### Add the four environment secrets

Return to **Settings → Environments → private → Environment secrets**. Choose
**Add secret** once for each row. Use these exact names, without quotes:

| Secret name | Exact source of its value |
| --- | --- |
| `DEPLOY_SSH_KEY` | Entire contents of `~/.ssh/polybot_deploy` from step 3, including the `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----` lines and real line breaks |
| `DEPLOY_KNOWN_HOSTS` | Entire contents of the repository's verified `known_hosts` file from step 4; it must include the exact `ansible_host` used by production inventory |
| `TS_OAUTH_CLIENT_ID` | Client ID copied from the Tailscale OpenID Connect credential just created |
| `TS_AUDIENCE` | Audience copied from that same credential, exactly as shown |

For the first two, **on your Mac/controller**, copy each file to the clipboard,
paste it into the corresponding secret's **Value**, and save before copying the
next file:

```sh
pbcopy < ~/.ssh/polybot_deploy
# Save as DEPLOY_SSH_KEY in GitHub, then copy the next value:
pbcopy < known_hosts
```

Use the private deployment key, not `polybot_deploy.pub`, your administrator's
key, or the server's host private key. Paste multiline values unchanged; do not
base64-encode them or replace line breaks with literal `\n` text.

All four belong under **Environment secrets**, because the workflows read
`secrets.NAME`. Although the Tailscale identifiers and verified host public keys
are not confidential, putting them under **Environment variables** would not
satisfy the current workflows. CI replaces its checked-out `known_hosts` with
`DEPLOY_KNOWN_HOSTS`; update both copies after a verified server host-key change.
No Vault password, SMTP password or manually created `GITHUB_TOKEN` is needed.

#### Allow release and container publication

Open **Settings → Actions → General** in the repository:

1. Ensure Actions are enabled. The action policy must allow `actions/*`,
   `astral-sh/setup-uv`, `docker/*`, and `tailscale/github-action`, plus this
   repository's reusable workflows. If using **Allow select actions and reusable
   workflows**, allow those owners/actions at the pinned revisions in the YAML.
2. Under **Workflow permissions**, the default **Read repository contents and
   packages permissions** can remain selected. The release workflow explicitly
   requests the permissions each job needs; there is no need to give every
   workflow write access by default. Leave **Allow GitHub Actions to create and
   approve pull requests** off; this release flow does not use it.

The existing workflow already declares:

| Job | Token permissions | Purpose |
| --- | --- | --- |
| `bundle` | `contents: write`, `packages: write` | Publish the GitHub Release and push backend/frontend images to GHCR |
| `deploy` | `contents: read`, `packages: read`, `id-token: write` | Read release content, pull images and obtain a GitHub OIDC token for Tailscale |

GitHub supplies `GITHUB_TOKEN` automatically for each job. Do not create a personal
access token for routine CI releases. If an organization policy blocks a required
action or publication, its administrator must allow that capability. See
[GitHub Actions permissions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).

**GHCR package access:** the workflow publishes these two packages:

```text
ghcr.io/hectortilla/polymarket-bots-backend
ghcr.io/hectortilla/polymarket-bots-frontend
```

In the owner's GitHub profile, open **Packages**, select each package, then
**Package settings → Manage Actions access**. Ensure `Polymarket-bots` has
**Write** or **Admin** access. If absent, choose **Add repository**, select
`Hectortilla/Polymarket-bots`, and set its role to **Write**.
That includes the read access deployment needs;
read-only package access would prevent later image publication even when the
workflow requests `packages: write`. Keep existing broader access for the
publishing repository rather than downgrading it to Read. See
[package access roles](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages).

**Packages do not exist yet?** That is normal before the first release. Publishing
with this repository's `GITHUB_TOKEN` automatically associates the new packages
with the repository. Check their access after step 7 first publishes them. For
pre-existing packages created another way, grant access before the release.
Keep package visibility private if that is your intended distribution policy;
do not make an image public to solve a permissions error. See
[package access and inheritance](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

#### Enable failure notifications for the operator

The operator is the person responsible for reacting to failed releases or lost
connectivity. For a single-person setup, use your GitHub account (`Hectortilla`)
and a verified email address you monitor:

1. While signed in as that operator, open the repository and choose
   **Watch → All Activity**.
2. Open your personal [notification settings](https://github.com/settings/notifications).
   Under **System → Actions**, enable **Email** and/or **On GitHub**, select
   **Only notify for failed workflows**, and save. Confirm the selected email
   address is the mailbox the operator checks.
3. Check delivery when a failed run occurs, including a scheduled
   **Daily private host connectivity** run. Each additional operator configures
   their own subscription; repository settings cannot select another user's
   personal notification preferences.

These are GitHub notifications. `polybot_alert_to` in inventory controls the
server's SMTP alerts and does not subscribe anyone to GitHub Actions failures.
See [GitHub Actions notification setup](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications).

#### Protect `master` and version tags

Open **Settings → Rules → Rulesets**. Use **New ruleset → New branch ruleset**
and configure this baseline:

| Field | Value |
| --- | --- |
| Ruleset name | `protect-master` |
| Enforcement status | **Active** |
| Target branches | **Include default branch** (`master`) |
| Bypass list | Empty for routine work |
| Rules | **Restrict deletions**, **Block force pushes**, **Require a pull request before merging**, **Require status checks to pass** |
| Required approvals within the pull-request rule | `0` for a solo maintainer; require a reviewer when a second maintainer is available |
| Required checks | `backend-browser / acceptance`, `frontend / verify`, `deployment / staging`, as reported by **Required validation** |

Select the checks emitted by an actual recent run, with GitHub Actions as their
source. If they are not offered yet, run validation on a branch/PR and return to
the selector. Require the three jobs, not just the workflow title. Leave
**Restrict updates** off for this branch, so normal PR merges can update it.
Do not require a successful deployment to `private` before merging: releases
deploy only after their commit is already in default-branch history.

Then create a **New tag ruleset** named `protect-release-tags`, set it to
**Active**, target tags matching `v*.*.*`, leave the bypass list empty, and enable
**Restrict updates** and **Restrict deletions**. Leave **Restrict creations** off
in this rule so you can push a new version tag. Existing versions must remain
fixed; publish a new version for a change. See
[creating rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
and [rule meanings](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).

Anyone with repository write access can still create a new version tag under
that baseline. If several people have write access and only the release operator
should create tags, add a **separate** tag ruleset for `v*.*.*` with **Restrict
creations**, allow only the release operator's eligible role/team to bypass that
rule, and disable other rules in it. Keep the update/deletion ruleset without
bypasses so creation permission does not also allow moving published tags.

#### Check the setup before the first release

Confirm the reviewed workflow files, populated public `production.yml`, and
verified `known_hosts` have reached `master`. Local-only files are unavailable to
Actions. Check that `private` lists all four secret names and both deployment
ref rules, and that the branch/tag rulesets are **Active**. Resolve any failing
**Required validation** jobs before tagging; release publication depends on those
same checks passing.

Open **Actions → Daily private host connectivity → Run workflow**, choose
`master`, and run it. It joins Tailscale and checks SSH plus HTTPS without
deploying or restarting the application. Inspect the individual steps:

| Result | Meaning and next action |
| --- | --- |
| Job rejected by environment policy | Allow branch `master` as well as version tags in `private` |
| Waiting for review | Remove required reviewers/wait timers if this environment is meant to run unattended |
| Tailscale authentication fails | Check the credential's issuer, exact subject, Client ID, audience, writable `auth_keys` scope and `tag:polybot-ci`; confirm both Tailscale values are environment secrets |
| SSH host verification fails | Check `DEPLOY_KNOWN_HOSTS` contains the verified key for the exact inventory hostname |
| SSH reports `Permission denied (publickey)` | Check `DEPLOY_SSH_KEY` matches the public key installed for `polybot` in step 5 |
| SSH succeeds, but HTTPS readiness fails before any release exists | Bootstrap has not started the application; proceed to step 7, then rerun this check and require a fully green result |
| Entire workflow succeeds | CI can reach the running application over the intended private route |

Before step 7, a failed final HTTPS probe can be expected, but a Tailscale or SSH
failure is not explained by the absence of an application release. The scheduled
check runs daily at **07:17 UTC** and uses these same settings. Its success does
not test GHCR publication/pulls; the first release verifies those permissions.

### 7. Deploy the first release

**Why:** Bootstrap prepared the server. Pushing a version tag now asks GitHub to
test, build, publish and deploy the application, including database migrations.

#### Tag the reviewed commit

Finish steps 1–6 and merge your deployment configuration into `master`. Wait for
**Required validation** to pass. **On your Mac/controller**, from the repository
root, fetch the latest state and inspect the commit you will release:

```sh
git fetch origin --tags
git log -1 --oneline origin/master
git tag --list v1.0.0
```

Use `v1.0.0` only if the last command prints nothing; otherwise choose the next
unused `vMAJOR.MINOR.PATCH` and replace it in both commands below. Tagging
`origin/master` explicitly selects the fetched default-branch commit, regardless
of your current local branch:

```sh
git tag v1.0.0 origin/master
git push origin v1.0.0
```

The push starts deployment. Do not use **Run workflow** for a brand-new version;
that option requires an already published release.

#### Follow the deployment in GitHub

Open **Actions → Private release** and select the run for your tag. Expect these
jobs to succeed in order:

| Job | What it does |
| --- | --- |
| `validate` | Runs backend, frontend, browser and deployment checks |
| `bundle` | Publishes the GHCR images and a GitHub Release containing `release.tar.gz` |
| `deploy` | Connects over Tailscale/OpenSSH, pulls the images, runs migrations and starts the application |

Wait for **deploy** to turn green; the existence of a GitHub Release alone does
not mean activation succeeded. Check the run summary's tag and commit, and verify
the two GHCR packages' Actions access as described in step 6. You do not need to
run Docker or Alembic commands manually.

#### Verify the running application

With your Mac connected to Tailscale, open the exact `polybot_origin` from
inventory, for example `https://hec-server.tailnet-name.ts.net`. Confirm the login
page loads over HTTPS, then verify login and email flows with your account.

**On your Mac/controller**, from the repository root:

```sh
export ANSIBLE_CONFIG="$PWD/deploy/ansible/ansible.cfg"
# Run this first ONLY if polybot_backups_enabled is true:
ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/backup.yml \
  --private-key ~/.ssh/polybot_deploy

# Run this for every deployment:
ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/status.yml \
  --private-key ~/.ssh/polybot_deploy -v
```

The backup establishes the first snapshot before status checks its freshness.
With backups disabled, skip that command. Status should finish with `failed=0`
and report `"failures": []`. These commands use the bootstrapped `polybot` account
and server-side secrets; no Vault or sudo password is needed.

Finally, run **Actions → Daily private host connectivity → Run workflow** from
`master`. Now both SSH and HTTPS must pass. Complete the
[external acceptance checks](#acceptance-and-removal-inventory), including recovery
verification if backups are enabled, before declaring setup complete.

#### If the release fails

- **Before publication:** inspect the first failed Actions step. Retry the
  original run after fixing external configuration; code or inventory changes
  require a new commit and version tag. For partial draft releases, follow
  [publication recovery](#routine-releases).
- **Published, but deployment failed:** fix the cause, then choose
  **Private release → Run workflow**, **Use workflow from: master**,
  `release_tag: v1.0.0` (your actual published tag), and `operation: deploy`.
  The workflow reuses the verified bundle.
- **Activation or migration failed:** inspect
  `sudo journalctl -u polybot-activate.service -n 100 --no-pager` **on the server**.
  See [database migrations](#database-migrations). There is no previous release
  to roll back to on a first deployment. Never move or overwrite the version tag.

Track CI usage against Tailscale Personal's current 1,000 ephemeral-resource
minutes per month; pause automation if the allowance is exhausted rather than
enabling paid capacity. Check [current Tailscale pricing](https://tailscale.com/pricing)
when reviewing usage.

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

## Database migrations

Alembic runs automatically on the server during release activation, including the
first deployment. It does not run during host bootstrap. Migration files and
`backend/alembic.ini` are included in the release's backend container image.

The GitHub **Private release** workflow triggers on a version tag such as `v1.0.0`,
or a manual deployment of a published release. Ansible stages the release and
starts `polybot-activate.service`. Its release executor then:

1. Starts PostgreSQL and Redis if needed and waits for them to be healthy,
   preserving existing containers and data volumes.
2. Stops web ingress and application processes before changing the database.
3. Runs a temporary `migrate` container from the candidate backend image. Its
   entrypoint calls Alembic's `upgrade(..., "head")`, applying revisions not yet
   recorded in the database, using the mounted database connection secret.
4. Starts API, worker and recovery services only after migration succeeds. Each
   application entrypoint checks that the database revision matches its image.
5. Restores web ingress after application readiness, then promotes the release.

The migration operation is equivalent to `alembic upgrade head`; you do not need
to SSH in and run it manually. The production executor supplies the selected
release's Compose file, image and credentials. See
[`BetaRelease.activate`](../scripts/beta_release/__init__.py) and
[`DeploymentSchema`](../backend/src/api/deployment/schema.py) for the implementation.

If migration fails, activation stops with ingress closed; repair the cause and
retry or deploy a reviewed forward repair. An application rollback runs a schema
compatibility check instead of migrations and never downgrades the database. The
older image must expect the database's current revision. Reapplying an already
active healthy release checks health without rerunning activation or migrations.

Inspect activation output **on the server**:

```sh
sudo journalctl -u polybot-activate.service -n 100 --no-pager
```

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
