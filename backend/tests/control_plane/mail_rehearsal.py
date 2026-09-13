"""Actual host alert transitions through rendered msmtp with authenticated STARTTLS."""

import shlex
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from scripts.host_operations import HostOperations
from scripts.host_operations.contracts import HostCheckCode, HostOperation


class MailSink:
    def __init__(self):
        self.messages = []
        self.reject_next = False
        self.authenticated = 0

    async def handle_DATA(self, server, session, envelope):
        if self.reject_next:
            self.reject_next = False
            return "451 temporary fixture rejection"
        self.messages.append(envelope.content)
        return "250 accepted"

    def authenticate(self, server, session, envelope, mechanism, credentials):
        accepted = (
            isinstance(credentials, LoginPassword)
            and credentials.login == b"fixture"
            and credentials.password == b"fixture-password"
        )
        if accepted:
            self.authenticated += 1
        return AuthResult(success=accepted, handled=False)


def main():
    root = Path(sys.argv[1])
    require_disposable_mail_host(root)
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
        # Trust the fixture CA in this disposable Debian host. The rendered
        # production msmtprc keeps certificate verification enabled throughout.
        Path("/usr/local/share/ca-certificates/polybot-rehearsal.crt").write_bytes(
            certificate.read_bytes()
        )
        subprocess.run(["update-ca-certificates"], check=True, capture_output=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        sink = MailSink()
        server = Controller(
            sink,
            hostname="127.0.0.1",
            port=1025,
            tls_context=context,
            require_starttls=True,
            auth_required=True,
            auth_require_tls=True,
            authenticator=sink.authenticate,
        )
        server.start()
        try:
            host = HostOperations(root)
            host.status = lambda: [HostCheckCode.APPLICATION]
            host.execute(HostOperation.MONITOR)
            host.execute(HostOperation.MONITOR)
            assert len(sink.messages) == 1
            host.status = list
            sink.reject_next = True
            try:
                host.execute(HostOperation.MONITOR)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("failed SMTP delivery was suppressed")
            host.execute(HostOperation.MONITOR)
            host.execute(HostOperation.MONITOR)
            assert len(sink.messages) == 2 and sink.authenticated == 3
            assert b"FAILURE" in sink.messages[0] and b"RECOVERY" in sink.messages[1]
            print(
                "Rendered msmtp + host alert path: authenticated STARTTLS, suppression, failure retry and recovery passed.",
                flush=True,
            )
        finally:
            server.stop()


def require_disposable_mail_host(root: Path) -> None:
    if (
        root != Path("/srv/polybot")
        or not Path("/etc/polybot-disposable-rehearsal").is_file()
    ):
        raise ValueError("mail rehearsal requires the disposable Debian fixture")
    host = HostOperations(root)
    if str(host.config.alert_to) != "operator@example.com":
        raise ValueError("mail rehearsal requires the fixture recipient")
    configuration = (root / "secrets" / "msmtprc").read_text().splitlines()
    settings = [shlex.split(line, comments=True) for line in configuration]
    for key, value in (
        ("account", "default"),
        ("host", "localhost"),
        ("port", "1025"),
        ("user", "fixture"),
        ("tls_starttls", "on"),
        ("auth", "on"),
    ):
        matches = [setting for setting in settings if setting and setting[0] == key]
        if matches != [[key, value]]:
            raise ValueError("mail rehearsal requires authenticated local fixture SMTP")


if __name__ == "__main__":
    main()
