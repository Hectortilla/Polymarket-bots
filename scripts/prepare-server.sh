#!/usr/bin/env bash
# Standalone Debian preparation; copy this file before running Ansible.
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ADMIN_USER=hec
KEY_LOGIN_VERIFIED=false
SWAPFILE=/swapfile
SWAP_MIB=2048
SWAPPINESS=10
SSHD_MAIN=/etc/ssh/sshd_config
SSHD_DROPIN=/etc/ssh/sshd_config.d/00-polybot-hardening.conf
SSH_ROLLBACK=false
WORKDIR=

main() {
    parse_arguments "$@"
    preflight
    WORKDIR=$(mktemp -d)
    trap cleanup EXIT
    trap 'echo "Preparation failed at line $LINENO; correct the error and rerun." >&2' ERR
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y sudo python3 ca-certificates curl openssh-server \
        ufw fail2ban unattended-upgrades
    usermod -aG sudo "$ADMIN_USER"
    visudo -c
    configure_swap
    configure_lid
    configure_updates
    harden_ssh
    configure_firewall_and_fail2ban
    enroll_tailscale
    swapon --show
    ufw status verbose
    fail2ban-client status sshd
    tailscale ip -4
    echo
    echo "Preparation complete. Open a NEW key-only SSH session as $ADMIN_USER and run sudo -v."
    echo 'Then continue docs/beta-deployment.md on your controller with Ansible.'
    echo 'Keep the current session open until the new connection works.'
}

parse_arguments() {
    while (($#)); do
        case "$1" in
            --admin-user)
                (($# >= 2)) || die '--admin-user requires a username.'
                ADMIN_USER=$2
                shift 2
                ;;
            --ssh-key-verified) KEY_LOGIN_VERIFIED=true; shift ;;
            -h|--help)
                cat <<'EOF'
Usage: sudo bash prepare-server.sh --ssh-key-verified [--admin-user hec]

Run on a Debian 12/13 systemd host as root (su - works if sudo is missing).
FIRST prove a fresh, non-multiplexed key-only SSH login to the non-root admin.
--ssh-key-verified acknowledges that this test succeeded; see the runbook.
The existing admin needs a local password for sudo and ~/.ssh/authorized_keys.
Installs sudo, security tools, Python and Tailscale; disables lid suspend;
hardens SSH; enables UFW, an SSH fail2ban jail and automatic updates;
creates/reuses 2 GiB /swapfile and persists swappiness=10.
Tailscale prints a browser login link: sign in as attosoria@hotmail.com.
Reruns preserve an already-connected Tailscale identity. No Ansible is run here.
EOF
                exit 0
                ;;
            *) die "Unknown argument: $1 (see --help)." ;;
        esac
    done
}

preflight() {
    [[ $EUID == 0 ]] || die 'Run as root using sudo or su -.'
    [[ $(uname -s) == Linux && -d /run/systemd/system ]] || die 'A Linux systemd host is required.'
    # shellcheck source=/dev/null
    source /etc/os-release
    [[ $ID == debian && ($VERSION_ID == 12 || $VERSION_ID == 13) ]] || die 'Only Debian 12/13 is supported.'
    [[ $ADMIN_USER =~ ^[a-z_][a-z0-9_-]*$ && $ADMIN_USER != root ]] || die 'Choose an existing non-root admin.'
    $KEY_LOGIN_VERIFIED || die 'First verify a new key-only admin login, then pass --ssh-key-verified.'
    local entry uid home shell password_state
    entry=$(getent passwd "$ADMIN_USER") || die "User $ADMIN_USER does not exist; create it first."
    IFS=: read -r _ _ uid _ _ home shell <<< "$entry"
    [[ $uid != 0 && $shell != */nologin && $shell != */false ]] || die 'The admin must have a non-root login shell.'
    password_state=$(passwd -S "$ADMIN_USER" | awk '{print $2}')
    [[ $password_state == P ]] || die "Set a local password with passwd $ADMIN_USER first; sudo needs it."
    ssh-keygen -l -f "$home/.ssh/authorized_keys" >/dev/null || die "No readable public keys for $ADMIN_USER. Run ssh-copy-id first."
    [[ -f $SSHD_MAIN && ! -L $SSHD_MAIN ]] || die 'Expected a regular /etc/ssh/sshd_config.'
    [[ ! -L $SSHD_DROPIN ]] || die 'The managed SSH drop-in must not be a symlink.'
    sshd -t
    SSH_PORTS=$(sshd -T | awk '$1 == "port" {print $2}')
    [[ -n $SSH_PORTS ]] || die 'Cannot determine configured OpenSSH ports.'
    # Include the actual session port for socket-activated or overridden sshd.
    if [[ -n ${SSH_CONNECTION:-} ]]; then
        read -r CLIENT_IP _ SERVER_IP SESSION_PORT <<< "$SSH_CONNECTION"
        [[ $SESSION_PORT =~ ^[0-9]+$ ]] || die 'Invalid SSH_CONNECTION port.'
        SSH_PORTS=$(printf '%s\n%s\n' "$SSH_PORTS" "$SESSION_PORT" | sort -un)
    fi
}

configure_swap() {
    local filesystem available signature
    filesystem=$(findmnt -no FSTYPE -T /)
    case "$filesystem" in
        ext2|ext3|ext4|xfs) ;;
        *) die "Swapfile creation supports ext2/3/4 or XFS, not $filesystem; configure swap separately." ;;
    esac
    [[ ! -L $SWAPFILE ]] || die "$SWAPFILE must not be a symlink."
    if [[ -e $SWAPFILE ]]; then
        [[ -f $SWAPFILE && $(stat -c %h "$SWAPFILE") == 1 ]] || die 'Swap must be a regular file with one link.'
        [[ $(stat -c %s "$SWAPFILE") == $((SWAP_MIB * 1024 * 1024)) ]] || die 'Existing /swapfile is not 2 GiB; it will not be resized.'
        signature=$(blkid -p -s TYPE -o value "$SWAPFILE") || die 'Existing /swapfile has no swap signature; refusing to overwrite it.'
        [[ $signature == swap ]] || die 'Existing /swapfile is not swap; refusing to overwrite it.'
    else
        available=$(df -Pk / | awk 'NR == 2 {print $4}')
        ((available >= (SWAP_MIB + 512) * 1024)) || die 'Need at least 2.5 GiB free for swap and headroom.'
        # dd allocates real blocks; fallocate can produce unsuitable extents.
        (umask 077; dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SWAP_MIB" status=progress)
        mkswap "$SWAPFILE"
    fi
    chown root:root "$SWAPFILE"
    chmod 600 "$SWAPFILE"
    if ! swapon --show=NAME --noheadings --raw | grep -Fxq "$SWAPFILE"; then
        swapon "$SWAPFILE"
    fi
    persist_swap
}

persist_swap() {
    # An active swapfile still needs persistence repaired on a rerun.
    if awk -v path="$SWAPFILE" '$1 == path {found=1} END {exit !found}' /etc/fstab; then
        awk -v path="$SWAPFILE" '
            $1 == path {count++; if ($3 != "swap" || $4 ~ /(^|,)noauto(,|$)/) bad=1}
            END {exit (count != 1 || bad)}' /etc/fstab || die 'Conflicting swap entry in /etc/fstab; correct it before rerunning.'
    else
        printf '\n%s none swap sw 0 0\n' "$SWAPFILE" >> /etc/fstab
    fi
    printf 'vm.swappiness=%s\n' "$SWAPPINESS" > /etc/sysctl.d/99-swappiness.conf
    sysctl -p /etc/sysctl.d/99-swappiness.conf
}

configure_lid() {
    mkdir -p /etc/systemd/logind.conf.d
    cat > /etc/systemd/logind.conf.d/99-server-lid.conf <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
EOF
    systemctl restart systemd-logind
    systemctl is-active --quiet systemd-logind
}

configure_updates() {
    cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
    systemctl enable --now apt-daily.timer apt-daily-upgrade.timer
    systemctl enable --now unattended-upgrades.service
}

harden_ssh() {
    cp -a "$SSHD_MAIN" "$WORKDIR/sshd_config"
    if [[ -e $SSHD_DROPIN ]]; then
        cp -a "$SSHD_DROPIN" "$WORKDIR/hardening.conf"
    fi
    SSH_ROLLBACK=true
    mkdir -p "$(dirname "$SSHD_DROPIN")"
    cat > "$SSHD_DROPIN" <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
    chmod 644 "$SSHD_DROPIN"
    # sshd uses the first value, so explicitly include our file before any
    # distribution/cloud drop-ins or an existing Match block.
    {
        printf 'Include %s\n' "$SSHD_DROPIN"
        awk -v line="Include $SSHD_DROPIN" '$0 != line' "$WORKDIR/sshd_config"
    } > "$SSHD_MAIN"
    sshd -t
    verify_ssh_policy
    # Reload preserves existing sessions. Roll back the files if it fails.
    systemctl reload ssh.service
    SSH_ROLLBACK=false
    echo 'SSH key-only policy validated and reloaded.'
}

verify_ssh_policy() {
    local effective
    effective=$(sshd -T)
    require_ssh_policy "$effective"
    if [[ -n ${SSH_CONNECTION:-} ]]; then
        effective=$(sshd -T -C "user=$ADMIN_USER,host=$CLIENT_IP,addr=$CLIENT_IP,laddr=$SERVER_IP,lport=$SESSION_PORT")
        require_ssh_policy "$effective"
    fi
}

require_ssh_policy() {
    local expected
    for expected in 'passwordauthentication no' 'kbdinteractiveauthentication no' \
        'permitrootlogin no' 'pubkeyauthentication yes'; do
        grep -Fxq "$expected" <<< "$1" || die "Effective SSH policy conflicts with: $expected."
    done
}

configure_firewall_and_fail2ban() {
    local port
    for port in $SSH_PORTS; do
        ufw allow "$port/tcp"
    done
    ufw default deny incoming
    ufw default allow outgoing
    ufw --force enable
    # journald works on minimal Debian without /var/log/auth.log or rsyslog.
    cat > /etc/fail2ban/jail.d/99-polybot-sshd.local <<EOF
[sshd]
enabled = true
backend = systemd
port = $(echo "$SSH_PORTS" | paste -sd, -)
EOF
    fail2ban-client -t
    systemctl enable fail2ban
    systemctl restart fail2ban
    wait_for_fail2ban
}

wait_for_fail2ban() {
    local attempt
    for ((attempt = 0; attempt < 10; attempt++)); do
        if fail2ban-client status sshd; then
            return
        fi
        sleep 1
    done
    die 'The fail2ban SSH jail did not become ready; inspect journalctl -u fail2ban.'
}

enroll_tailscale() {
    if ! command -v tailscale >/dev/null; then
        mkdir -p /usr/share/keyrings
        curl --fail --silent --show-error --location \
            "https://pkgs.tailscale.com/stable/debian/$VERSION_CODENAME.noarmor.gpg" \
            -o "$WORKDIR/tailscale.gpg"
        install -m 644 "$WORKDIR/tailscale.gpg" /usr/share/keyrings/tailscale-archive-keyring.gpg
        printf 'deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/debian %s main\n' \
            "$VERSION_CODENAME" > /etc/apt/sources.list.d/tailscale.list
        apt-get update
        apt-get install -y tailscale
    fi
    systemctl enable --now tailscaled
    local state
    state=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["BackendState"])')
    case "$state" in
        Running)
            echo 'Keeping the existing Tailscale enrollment. Verify its tailnet in the admin console.'
            tailscale set --ssh=false
            ;;
        NeedsLogin|NoState)
            echo 'Open the Tailscale URL below on your laptop and sign in as attosoria@hotmail.com.'
            tailscale up --ssh=false --timeout=5m
            ;;
        *) die "Tailscale state is $state; resolve it with tailscale status/admin console and rerun." ;;
    esac
    state=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["BackendState"])')
    [[ $state == Running ]] || die "Tailscale is $state; finish device approval and rerun."
    echo 'In the admin console, verify the tailnet and apply the deployment host tag from the runbook before Ansible.'
}

cleanup() {
    local status=$?
    if $SSH_ROLLBACK; then
        cp -a "$WORKDIR/sshd_config" "$SSHD_MAIN"
        if [[ -e $WORKDIR/hardening.conf ]]; then
            cp -a "$WORKDIR/hardening.conf" "$SSHD_DROPIN"
        else
            rm -f "$SSHD_DROPIN"
        fi
        echo 'Restored previous SSH files; hardening did not complete.' >&2
    fi
    [[ -z $WORKDIR ]] || rm -rf "$WORKDIR"
    return "$status"
}

die() { echo "ERROR: $*" >&2; exit 1; }

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
