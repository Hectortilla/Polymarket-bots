"""Exercise standalone preparation failure paths without changing the test host."""

import os
import subprocess

import pytest

from scripts.deployment.paths import REPOSITORY

SCRIPT = REPOSITORY / "scripts" / "prepare-server.sh"
SSH_POLICY = """passwordauthentication no
kbdinteractiveauthentication no
permitrootlogin no
pubkeyauthentication yes"""


@pytest.fixture
def preparation(tmp_path):
    etc = tmp_path / "etc"
    (etc / "ssh" / "sshd_config.d").mkdir(parents=True)
    (etc / "sysctl.d").mkdir()
    (etc / "fail2ban" / "jail.d").mkdir(parents=True)
    (etc / "fstab").write_text("# existing mounts\n")
    (etc / "ssh" / "sshd_config").write_text("PasswordAuthentication yes\n")
    # Redirect literal system paths only in the disposable copy. Production has
    # no environment override that could accidentally target another root.
    script = tmp_path / "prepare.sh"
    script.write_text(SCRIPT.read_text().replace("/etc/", f"{etc}/"))
    harness = tmp_path / "harness.sh"
    harness.write_text(
        """source "$1"
WORKDIR=$(mktemp -d)
trap cleanup EXIT
systemctl() { echo "systemctl $*" >> "$CALLS"; [[ ${RELOAD_FAIL:-false} != true ]]; }
sshd() {
    if [[ $1 == -t ]]; then
        [[ ${SYNTAX_FAIL:-false} != true ]]
    elif [[ ${POLICY_FAIL:-false} == true ]]; then
        echo 'passwordauthentication yes'
    else
        printf '%s\\n' "$SSH_POLICY"
    fi
}
sysctl() { echo "sysctl $*" >> "$CALLS"; }
ufw() { echo "ufw $*" >> "$CALLS"; }
fail2ban-client() { echo "fail2ban $*" >> "$CALLS"; }
findmnt() { echo "${FILESYSTEM:-ext4}"; }
stat() { if [[ $2 == %h ]]; then echo 1; else echo "${FILE_SIZE:-2147483648}"; fi; }
blkid() { echo "${SIGNATURE:-swap}"; }
chown() { :; }
swapon() {
    if [[ $1 == --show=NAME ]]; then
        echo "$SWAPFILE"
    else
        echo "swapon $*" >> "$CALLS"
    fi
}
tailscale() {
    echo "tailscale $*" >> "$CALLS"
    if [[ $1 == status ]]; then
        echo "{\\"BackendState\\": \\"${TAILSCALE_STATE:-Running}\\"}"
    fi
}
eval "$2"
"""
    )
    calls = tmp_path / "calls"
    calls.touch()

    def run(body, **variables):
        return subprocess.run(
            ["bash", str(harness), str(script), body],
            env={
                **os.environ,
                "CALLS": str(calls),
                "SSH_POLICY": SSH_POLICY,
                **variables,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    return tmp_path, run


@pytest.mark.parametrize("failure", ["SYNTAX_FAIL", "POLICY_FAIL", "RELOAD_FAIL"])
@pytest.mark.parametrize("existing_dropin", [False, True])
def test_ssh_failure_restores_both_files(preparation, failure, existing_dropin):
    root, run = preparation
    main = root / "etc/ssh/sshd_config"
    dropin = root / "etc/ssh/sshd_config.d/00-polybot-hardening.conf"
    before = main.read_text()
    if existing_dropin:
        dropin.write_text("# retained original\n")
    result = run("harden_ssh", **{failure: "true"})
    assert result.returncode != 0
    assert main.read_text() == before
    assert dropin.exists() == existing_dropin
    if existing_dropin:
        assert dropin.read_text() == "# retained original\n"
    assert "Restored previous SSH files" in result.stderr
    if failure != "RELOAD_FAIL":
        assert "systemctl reload" not in (root / "calls").read_text()


def test_ssh_rerun_preserves_config_without_duplicate_include(preparation):
    root, run = preparation
    result = run("harden_ssh; harden_ssh")
    assert result.returncode == 0, result.stderr
    main = (root / "etc/ssh/sshd_config").read_text().splitlines()
    assert len(main) == 2
    assert main[0].startswith("Include ")
    assert main[1] == "PasswordAuthentication yes"


def test_active_swap_repairs_persistence_once(preparation):
    root, run = preparation
    swap = root / "swapfile"
    swap.write_text("existing swap contents")
    result = run(
        'SWAPFILE="$SWAP_PATH"; configure_swap; configure_swap', SWAP_PATH=str(swap)
    )
    assert result.returncode == 0, result.stderr
    assert (root / "etc/fstab").read_text().count(f"{swap} none swap sw 0 0") == 1
    assert (
        root / "etc/sysctl.d/99-swappiness.conf"
    ).read_text() == "vm.swappiness=10\n"
    assert "swapon " not in (root / "calls").read_text()
    assert swap.read_text() == "existing swap contents"


@pytest.mark.parametrize(
    "variables",
    [{"FILESYSTEM": "btrfs"}, {"FILE_SIZE": "1024"}, {"SIGNATURE": "ext4"}],
)
def test_unsupported_swap_is_not_overwritten(preparation, variables):
    root, run = preparation
    swap = root / "swapfile"
    swap.write_text("preserve me")
    result = run(
        'SWAPFILE="$SWAP_PATH"; configure_swap', SWAP_PATH=str(swap), **variables
    )
    assert result.returncode != 0
    assert swap.read_text() == "preserve me"
    assert (root / "etc/fstab").read_text() == "# existing mounts\n"


def test_swap_symlink_is_rejected(preparation):
    root, run = preparation
    target = root / "other-file"
    target.write_text("preserve me")
    swap = root / "swapfile"
    swap.symlink_to(target)
    result = run('SWAPFILE="$SWAP_PATH"; configure_swap', SWAP_PATH=str(swap))
    assert result.returncode != 0
    assert target.read_text() == "preserve me"


def test_conflicting_fstab_stops_instead_of_duplicating(preparation):
    root, run = preparation
    fstab = root / "etc/fstab"
    fstab.write_text("/swapfile none swap noauto 0 0\n")
    result = run("persist_swap")
    assert result.returncode != 0
    assert fstab.read_text() == "/swapfile none swap noauto 0 0\n"


def test_all_ssh_ports_allowed_before_firewall_enable(preparation):
    root, run = preparation
    result = run("SSH_PORTS=$'22\\n2222'; configure_firewall_and_fail2ban")
    assert result.returncode == 0, result.stderr
    calls = (root / "calls").read_text().splitlines()
    for port in (22, 2222):
        assert calls.index(f"ufw allow {port}/tcp") < calls.index("ufw --force enable")
    jail = (root / "etc/fail2ban/jail.d/99-polybot-sshd.local").read_text()
    assert "backend = systemd" in jail
    assert "port = 22,2222" in jail


def test_existing_tailnet_identity_is_retained(preparation):
    root, run = preparation
    result = run("enroll_tailscale")
    assert result.returncode == 0, result.stderr
    calls = (root / "calls").read_text()
    assert "tailscale set --ssh=false" in calls
    assert "tailscale up" not in calls


def test_tailnet_approval_failure_is_not_reported_as_success(preparation):
    root, run = preparation
    result = run("enroll_tailscale", TAILSCALE_STATE="NeedsMachineAuth")
    assert result.returncode != 0
    assert "NeedsMachineAuth" in result.stderr
    assert "tailscale up" not in (root / "calls").read_text()


def test_first_tailnet_login_waits_for_running_state(preparation):
    root, run = preparation
    result = run(
        """
tailscale() {
    echo "tailscale $*" >> "$CALLS"
    if [[ $1 == up ]]; then
        touch "$WORKDIR/enrolled"
    elif [[ $1 == status && -f $WORKDIR/enrolled ]]; then
        echo '{"BackendState":"Running"}'
    elif [[ $1 == status ]]; then
        echo '{"BackendState":"NeedsLogin"}'
    fi
}
enroll_tailscale
"""
    )
    assert result.returncode == 0, result.stderr
    assert "tailscale up --ssh=false --timeout=5m" in (root / "calls").read_text()


def test_failed_firewall_allow_does_not_enable_firewall(preparation):
    root, run = preparation
    result = run(
        """
ufw() { echo "ufw $*" >> "$CALLS"; [[ $1 != allow ]]; }
SSH_PORTS=2222
configure_firewall_and_fail2ban
"""
    )
    assert result.returncode != 0
    assert "ufw --force enable" not in (root / "calls").read_text()


def test_insufficient_disk_space_does_not_create_swap(preparation):
    root, run = preparation
    swap = root / "swapfile"
    result = run(
        """
df() { printf 'Filesystem blocks used available capacity mount\\n/dev/test 1000 900 100 90%% /\\n'; }
SWAPFILE="$SWAP_PATH"
configure_swap
""",
        SWAP_PATH=str(swap),
    )
    assert result.returncode != 0
    assert "2.5 GiB" in result.stderr
    assert not swap.exists()


def test_help_requires_no_root_or_host_changes():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "--ssh-key-verified" in result.stdout
