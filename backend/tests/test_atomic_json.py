from pathlib import Path
from unittest.mock import patch

import pytest
from polybot.persistence.atomic_json import AtomicJsonFile


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), object()])
def test_invalid_write_preserves_state_without_temporary_files(
    tmp_path: Path, invalid: object
) -> None:
    path = tmp_path / "state.json"
    store = AtomicJsonFile(path)
    store.write({"saved": "café"})
    original = path.read_bytes()
    with pytest.raises((TypeError, ValueError)):
        store.write({"invalid": invalid})
    assert path.read_bytes() == original
    assert store.read() == {"saved": "café"}
    assert list(tmp_path.iterdir()) == [path]


def test_failed_replace_cleans_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = AtomicJsonFile(path)
    store.write({"saved": True})
    with patch(
        "polybot.persistence.atomic_json.os.replace", side_effect=OSError("unavailable")
    ):
        with pytest.raises(OSError, match="unavailable"):
            store.write({"saved": False})
    assert store.read() == {"saved": True}
    assert list(tmp_path.iterdir()) == [path]
