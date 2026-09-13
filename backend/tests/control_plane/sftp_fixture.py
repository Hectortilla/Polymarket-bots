"""Disposable real SFTP server using rclone, with independently known host keys."""

import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from scripts.beta_backup.remote import RemoteBackups


@contextmanager
def sftp_server(directory: Path):
    directory.mkdir(mode=0o700, exist_ok=True)
    key = directory / "client"
    host = directory / "host"
    for path in (key, host):
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True
        )
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    storage = directory / "storage"
    storage.mkdir(mode=0o700)
    (storage / "polybot").mkdir(mode=0o700)
    known = directory / "known_hosts"
    known.write_text(f"[127.0.0.1]:{port} " + host.with_suffix(".pub").read_text())
    known.chmod(0o600)
    config = directory / "rclone.conf"
    config.write_text(
        f"[backup]\ntype = sftp\nhost = 127.0.0.1\nport = {port}\nuser = fixture\nkey_file = {key}\nknown_hosts_file = {known}\ndisable_hashcheck = true\nshell_type = none\n"
    )
    config.chmod(0o600)
    log = (directory / "server.log").open("wb")
    process = subprocess.Popen(
        [
            "rclone",
            "serve",
            "sftp",
            str(storage),
            "--addr",
            f"127.0.0.1:{port}",
            "--key",
            str(host),
            "--authorized-keys",
            str(key.with_suffix(".pub")),
            "--user",
            "fixture",
            "--dir-cache-time",
            "0s",
        ],
        stdout=log,
        stderr=log,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("disposable SFTP server failed")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        remote = RemoteBackups(config, "backup:/polybot", directory)
        yield remote, storage / "polybot", process
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()
