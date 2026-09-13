"""Disposable STARTTLS delivery through the installed msmtp binary."""

import ssl
import subprocess
import tempfile
from pathlib import Path

from aiosmtpd.controller import Controller


class MailSink:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope.content)
        return "250 accepted"


def main():
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        certificate, key = directory / "mail.crt", directory / "mail.key"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            capture_output=True,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        sink = MailSink()
        server = Controller(
            sink,
            hostname="127.0.0.1",
            port=1025,
            tls_context=context,
            require_starttls=True,
        )
        server.start()
        try:
            config = directory / "msmtprc"
            config.write_text(
                f"account default\nhost localhost\nport 1025\nauth off\ntls on\ntls_starttls on\ntls_trust_file {certificate}\nfrom fixture@example.com\n"
            )
            config.chmod(0o600)
            for state in ("FAILURE", "RECOVERY"):
                subprocess.run(
                    ["msmtp", "--file", str(config), "--", "operator@example.com"],
                    input=f"To: operator@example.com\nSubject: Polybot {state}\n\nDisposable check.\n",
                    text=True,
                    check=True,
                    timeout=10,
                )
            assert len(sink.messages) == 2
            assert b"FAILURE" in sink.messages[0] and b"RECOVERY" in sink.messages[1]
            print("Disposable msmtp STARTTLS failure/recovery delivery passed.")
        finally:
            server.stop()


if __name__ == "__main__":
    main()
