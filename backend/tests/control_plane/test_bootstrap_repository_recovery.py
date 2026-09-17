"""Exercise bootstrap's legacy repository repair without touching system APT."""

import copy
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("existing", [False, True])
def test_repository_recovery_preserves_other_entries_and_is_idempotent(
    tmp_path, existing
):
    executable = shutil.which("ansible-playbook")
    if executable is None:
        pytest.skip("ansible-playbook is required for the local recovery check")
    tasks = yaml.safe_load(Path("deploy/ansible/bootstrap.yml").read_text())[0]["tasks"]
    repair = next(task for task in tasks if task.get("register") == "legacy_source")
    first_apt = next(
        task for task in tasks if task.get("register") == "minimal_packages"
    )
    assert tasks.index(repair) < tasks.index(first_apt)

    repair = copy.deepcopy(repair)
    script = repair["ansible.builtin.raw"]
    source_assignment = next(
        line for line in script.splitlines() if line.startswith("legacy=")
    )
    source = tmp_path / "sources with spaces.list"
    repair["ansible.builtin.raw"] = script.replace(
        source_assignment, f"legacy={shlex.quote(str(source))}", 1
    )
    repair["become"] = False
    legacy_entry = (
        "deb [signed-by=/etc/apt/keyrings/tailscale.gpg] "
        "https://pkgs.tailscale.com/stable/debian trixie main"
    )
    retained = "# Operator-managed entry\ndeb https://example.com/debian trixie main\n"
    if existing:
        source.write_text(retained + legacy_entry + "\n")

    playbook = tmp_path / "repair.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "ansible_python_interpreter": sys.executable,
                        "ansible_distribution_release": "trixie",
                    },
                    "tasks": [
                        repair,
                        {
                            "ansible.builtin.assert": {
                                "that": [f"legacy_source.changed == {existing}"]
                            },
                        },
                        repair,
                        {
                            "ansible.builtin.assert": {
                                "that": ["not legacy_source.changed"]
                            },
                        },
                    ],
                }
            ]
        )
    )
    result = subprocess.run(
        [executable, "-i", "localhost,", str(playbook)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if existing:
        assert source.read_text() == retained
        backups = list(tmp_path.glob(source.name + ".*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text() == retained + legacy_entry + "\n"
    else:
        assert not source.exists()
