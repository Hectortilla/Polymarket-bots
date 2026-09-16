"""Exercise bootstrap's legacy repository repair without touching system APT."""

import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined


@pytest.mark.parametrize("existing", [False, True])
def test_repository_recovery_preserves_other_entries_and_is_idempotent(
    tmp_path, existing
):
    executable = shutil.which("ansible-playbook")
    if executable is None:
        pytest.skip("ansible-playbook is required for the local recovery check")
    tasks = yaml.safe_load(Path("deploy/ansible/bootstrap.yml").read_text())[0]["tasks"]
    repair = next(task for task in tasks if "ansible.builtin.lineinfile" in task)
    first_apt = next(task for task in tasks if "ansible.builtin.apt" in task)
    assert tasks.index(repair) < tasks.index(first_apt)

    repair = copy.deepcopy(repair)
    module = repair["ansible.builtin.lineinfile"]
    source = tmp_path / Path(module["path"]).name
    module["path"] = str(source)
    legacy_entry = (
        Environment(undefined=StrictUndefined)
        .from_string(module["line"])
        .render(ansible_distribution_release="trixie")
    )
    retained = "# Operator-managed entry\ndeb https://example.com/debian trixie main\n"
    if existing:
        source.write_text(retained + legacy_entry + "\n")

    repeat = copy.deepcopy(repair) | {"register": "repeated_repair"}
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
                        repeat,
                        {
                            "ansible.builtin.assert": {
                                "that": ["not repeated_repair.changed"]
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
        backups = list(tmp_path.glob(source.name + ".*~"))
        assert len(backups) == 1
        assert backups[0].read_text() == retained + legacy_entry + "\n"
    else:
        assert not source.exists()
