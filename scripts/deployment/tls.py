"""Capture regular TLS files and validate exactly the bytes installed on the host."""

import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scripts.deployment.storage import SecretFile
from scripts.private_files import read_regular, write_private


@dataclass(frozen=True)
class TlsMaterial:
    certificate: bytes
    private_key: bytes

    @classmethod
    def from_paths(cls, certificate: Path, private_key: Path) -> "TlsMaterial":
        material = cls(read_regular(certificate), read_regular(private_key))
        # OpenSSL only accepts paths. Validate private snapshots so source file
        # replacement cannot block validation or change what gets installed.
        with tempfile.TemporaryDirectory(prefix="polybot-tls-") as temporary:
            directory = Path(temporary)
            cert = directory / SecretFile.TLS_CERT
            key = directory / SecretFile.TLS_KEY
            write_private(cert, material.certificate)
            write_private(key, material.private_key)
            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(
                cert, key, password=""
            )
        return material
