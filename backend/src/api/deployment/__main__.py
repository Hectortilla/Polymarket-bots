"""Validated container entrypoints; never log configuration or secret values."""

import argparse
import asyncio
import os
import sys

from api.deployment.schema import DeploymentSchema
from api.deployment.settings import API_PORT, API_WORKERS, StartupSettings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=("api", "worker", "migrate", "check"))
    service = parser.parse_args().service
    try:
        settings = StartupSettings.from_env()
    except ValueError as error:
        sys.exit(f"deployment configuration invalid: {error}")
    schema = DeploymentSchema(settings)
    if service == "migrate":
        try:
            schema.migrate()
        except Exception:
            # Driver/migration exceptions may contain connection or row values.
            sys.exit("deployment migration failed; application activation refused")
        return
    try:
        asyncio.run(schema.require_compatible())
    except Exception:
        sys.exit(
            "deployment schema check failed; verify database availability and release compatibility"
        )
    if service == "check":
        return
    if service == "api":
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "api.http.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(API_PORT),
            "--workers",
            str(API_WORKERS),
            "--no-access-log",
        ]
        command += (
            ["--proxy-headers", "--forwarded-allow-ips", settings.proxy_address]
            if settings.proxy_address
            else ["--no-proxy-headers"]
        )
    else:
        command = [
            "taskiq",
            "worker",
            "api.execution.taskiq_app:broker",
            "--workers",
            "1",
            "--max-async-tasks",
            str(settings.worker_concurrency),
        ]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
