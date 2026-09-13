"""Prepare ~/app with the release Compose file, private settings and runtime secrets."""

import argparse
import getpass
import os
import secrets
import tempfile
from pathlib import Path

from api.auth.config import AuthSettings
from api.auth.mail.config import DEFAULT_SMTP_SECURITY, SmtpSecurity, SmtpSettings
from pydantic import SecretStr

from scripts.deployment.dotenv import write_manifest
from scripts.deployment.images import ReleaseImages
from scripts.deployment.manifest import (
    DEFAULT_AUTH_ORIGIN,
    DEFAULT_SMTP_PORT,
    RuntimeManifest,
)
from scripts.deployment.paths import (
    DEFAULT_APP_DIRECTORY,
    HOST_COMPOSE_NAME,
    MANIFEST_NAME,
    REPOSITORY,
    SECRETS_DIRECTORY_NAME,
)
from scripts.deployment.source import compose_for_release
from scripts.deployment.storage import (
    CONTAINER_SECRET_MODE,
    SecretFile,
    database_url,
    redis_url,
)
from scripts.deployment.tls import TlsMaterial
from scripts.private_files import (
    PRIVATE_DIRECTORY_MODE,
    sync_directory,
    write_private,
)

HOST_SMTP_SECURITY = (SmtpSecurity.STARTTLS, SmtpSecurity.TLS)


def setup(
    app_dir: Path,
    image_manifest: Path,
    origin: str,
    smtp: SmtpSettings,
    tls_cert: Path,
    tls_key: Path,
) -> None:
    if app_dir.is_symlink():
        raise ValueError("app directory must not be a symlink")
    app_dir = app_dir.resolve()
    if app_dir.is_relative_to(REPOSITORY):
        raise ValueError("runtime secrets must be outside the repository")
    if app_dir.exists() and any(app_dir.iterdir()):
        raise ValueError(
            "app directory is not empty; use beta_start --release for updates"
        )
    images = ReleaseImages.read(image_manifest)
    auth = AuthSettings(origin)
    compose_yaml = compose_for_release(images.source_commit)
    tls = TlsMaterial.from_paths(tls_cert, tls_key)
    if smtp.security not in HOST_SMTP_SECURITY:
        raise ValueError("host setup requires TLS SMTP")
    username = smtp.username.get_secret_value() if smtp.username else ""
    password = smtp.password.get_secret_value() if smtp.password else ""
    if not username.strip() or not password.strip():
        raise ValueError("SMTP username and password are required")
    if username != username.strip() or password != password.strip():
        raise ValueError("SMTP credentials must not have surrounding whitespace")
    database_password = secrets.token_hex(32)
    settings = RuntimeManifest(images, auth, smtp, app_dir / SECRETS_DIRECTORY_NAME)
    app_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".polybot-setup-", dir=app_dir.parent
    ) as temporary:
        staging = Path(temporary) / "app"
        staging.mkdir(mode=PRIVATE_DIRECTORY_MODE)
        secret_dir = staging / SECRETS_DIRECTORY_NAME
        secret_dir.mkdir(mode=PRIVATE_DIRECTORY_MODE)
        secret_values = {
            SecretFile.POSTGRES_PASSWORD: database_password.encode(),
            SecretFile.DATABASE_URL: database_url(database_password).encode(),
            SecretFile.REDIS_URL: redis_url().encode(),
            SecretFile.SMTP_USERNAME: username.encode(),
            SecretFile.SMTP_PASSWORD: password.encode(),
            SecretFile.TLS_CERT: tls.certificate,
            SecretFile.TLS_KEY: tls.private_key,
        }
        for name, content in secret_values.items():
            # Bind-mounted secrets keep host ownership. The private parent
            # prevents host traversal; file readability permits backend UID 10001.
            write_private(secret_dir / name, content, mode=CONTAINER_SECRET_MODE)
        write_manifest(staging / MANIFEST_NAME, settings.to_values())
        write_private(staging / HOST_COMPOSE_NAME, compose_yaml)
        os.replace(staging, app_dir)
        sync_directory(app_dir.parent)
    print(f"Prepared {app_dir}; .env is mode 600. No containers were started.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release", type=Path, required=True, help="published image manifest"
    )
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIRECTORY)
    parser.add_argument("--origin", default=DEFAULT_AUTH_ORIGIN)
    parser.add_argument("--tls-cert", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--smtp-host", required=True)
    parser.add_argument("--smtp-from", required=True)
    parser.add_argument("--smtp-port", type=int, default=DEFAULT_SMTP_PORT)
    parser.add_argument(
        "--smtp-security",
        choices=HOST_SMTP_SECURITY,
        default=DEFAULT_SMTP_SECURITY,
    )
    args = parser.parse_args()
    smtp = SmtpSettings(
        host=args.smtp_host,
        port=args.smtp_port,
        sender=args.smtp_from,
        security=args.smtp_security,
        username=SecretStr(getpass.getpass("SMTP username: ")),
        password=SecretStr(getpass.getpass("SMTP password: ")),
    )
    setup(args.app_dir, args.release, args.origin, smtp, args.tls_cert, args.tls_key)


if __name__ == "__main__":
    main()
