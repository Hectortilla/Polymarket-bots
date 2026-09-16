# Prepare the server before Ansible

**Do this first on the server, before Ansible or application deployment.** Copy
only [`scripts/prepare-server.sh`](../scripts/prepare-server.sh); no checkout,
Python environment, Ansible installation or existing sudo package is needed on
the server. It targets Debian 12/13 with systemd and an existing non-root account
(`hec` by default). Initial OpenSSH access and root access through `su -`, sudo,
or the console are required. Set the final machine hostname before enrolling
Tailscale so the later inventory can use the intended DNS name.

## Copy and run

From your laptop, verify the server's host key through the console/provider,
then install your public key and prove a **new key-only connection**. Replace
`SERVER` and the key path; for custom SSH ports add `-p PORT` to SSH/ssh-copy-id
and `-P PORT` to scp:

```sh
ssh-copy-id -i ~/.ssh/id_ed25519.pub hec@SERVER
ssh -o ControlMaster=no -o ControlPath=none -o PreferredAuthentications=publickey \
  -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 hec@SERVER 'id -un'
scp scripts/prepare-server.sh hec@SERVER:prepare-server.sh
ssh -t hec@SERVER
```

The key-only command must print `hec`. Keep this SSH session open throughout.
The script checks that the selected account has a parseable authorized key and a
local password, but only that connection test proves you possess a working key.
The password remains necessary for sudo after SSH password authentication is
disabled. If needed, create the account using `adduser hec` and set its password
using `passwd hec` from a root console first, then install and test the key.

On the server, if sudo already works:

```sh
sudo bash "$HOME/prepare-server.sh" --admin-user hec --ssh-key-verified
```

If sudo is missing or `hec` is not yet allowed to use it, become root first:

```sh
su -
bash /home/hec/prepare-server.sh --admin-user hec --ssh-key-verified
```

If neither sudo nor `su -` is available, use the server console's root access.
The script installs sudo and adds `hec` to the sudo group; a fresh login picks up
the new membership. The flag acknowledges the successful key-only login above.
Use `--admin-user OTHER_USER` for another existing non-root administrator.

## What it configures

- Installs sudo, Python 3 for Ansible, and the host security packages.
- Creates/reuses a 2 GiB `/swapfile`, persists it in `/etc/fstab`, and sets
  `vm.swappiness=10`. It supports ext2/3/4 and XFS, needs 2.5 GiB free for a new
  file, and refuses symlinks, conflicting fstab entries, and existing files with
  an unexpected size or signature. It repairs persistence even when swap is
  already active. Other filesystems, including Btrfs, stop preparation for manual
  handling; this script does not implement their special swapfile requirements.
- Sets all three logind lid actions to `ignore` in
  `/etc/systemd/logind.conf.d/99-server-lid.conf` and restarts logind. Run over SSH;
  the restart may affect local desktop sessions. Desktop power managers can also
  control lid behavior, so test closing the lid on the actual laptop.
- Enables the APT daily timers and unattended upgrades using the distribution's
  allowed update origins. It does not add an automatic reboot policy.
- Disables password/keyboard-interactive SSH and root SSH login, keeps public-key
  login enabled, validates configuration and effective settings, then reloads SSH.
  Its dedicated Include is prepended to `sshd_config` because OpenSSH uses the
  first value. It also checks the current connection's address context when
  `SSH_CONNECTION` is available, and restores the old files if validation or
  reload fails. Existing custom Match/access rules may still need manual
  adjustment; the fresh connection test remains required.
- Allows the configured SSH TCP ports (plus the current connection port when
  available) before enabling UFW with deny-incoming/allow-outgoing defaults.
  Existing UFW rules are retained. Enables an explicit fail2ban SSH jail using
  journald, including on minimal Debian without `/var/log/auth.log`.
- Installs Tailscale from its signed stable Debian repository and starts it.
  On first enrollment, open the printed browser link and sign in as
  **attosoria@hotmail.com**. Complete any device approval. An already-connected
  device retains its enrollment; check its tailnet in the admin console.
  Ordinary OpenSSH is used; Tailscale SSH is disabled.

Tailscale browser authentication is the interactive step; the script cannot log
in to your account for you. If it times out after five minutes, complete the
browser/device approval and rerun the same command. Other errors also stop the
script; completed steps remain in place and can be rerun. An interrupted new
swapfile without a swap signature is deliberately not overwritten: inspect it
before removing an incomplete file and retrying. Existing swap is never resized.

There are no new public 80/443 firewall rules: this repository uses Tailscale
Serve for private HTTPS. UFW does not replace tailnet policy or Docker network
controls; retain Compose's loopback-only application binding. The script does not
install or configure Cloudflare Tunnel.

## Verify, then continue with Ansible

Open a **second** key-only SSH session using the command above (omit `'id -un'`
to keep the session interactive), then run:

```sh
sudo -v
sudo ufw status verbose
sudo fail2ban-client status sshd
swapon --show
systemctl list-timers 'apt-daily*'
tailscale status
```

Keep the old session until both the fresh login and sudo work. A later reboot
should retain swap, update timers and Tailscale connectivity. On the actual
laptop, also verify SSH remains reachable with the lid closed.

Continue [one-time deployment setup](beta-deployment.md#one-time-setup): apply
`tag:polybot` to this enrolled server in the Tailscale admin console, configure
policy/MagicDNS/HTTPS, and set the exact private origin in inventory. Ansible
keeps an already-running enrollment, so apply the tag explicitly after browser
login. The current bootstrap validator still requires `polybot_tailscale_authkey`
in Vault even when the device is connected; supply the tagged key described in
the runbook, which is used only if enrollment is needed. Ansible installs Docker,
the deployment account and application infrastructure, and configures Serve.
After tailnet OpenSSH is verified, restrict initial public/LAN SSH as appropriate.

References: [OpenSSH configuration precedence](https://man.openbsd.org/sshd_config),
[swapfile restrictions](https://man7.org/linux/man-pages/man8/swapon.8.html),
[Tailscale Debian packages](https://pkgs.tailscale.com/stable/), and
[Tailscale browser enrollment](https://tailscale.com/docs/install/linux).
