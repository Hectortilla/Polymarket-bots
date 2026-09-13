"""Pull and activate a private release, resuming any interrupted deployment attempt."""

import argparse
from pathlib import Path

from scripts import ghcr
from scripts.beta_release import BetaRelease
from scripts.compose_project import DEFAULT_COMPOSE_PROJECT, ComposeProject
from scripts.deployment.attempt import AttemptPhase
from scripts.deployment.images import ImagePolicy, ReleaseImages
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import DEFAULT_APP_DIRECTORY
from scripts.deployment.source import compose_for_release
from scripts.deployment.state import DeploymentState
from scripts.private_files import PRIVATE_FILE_MODE

LOG_TAIL_LINES = 100


def start(
    app_dir: Path,
    username: str,
    *,
    image_manifest: Path | None = None,
    follow_logs: bool = True,
    rollback: bool = False,
) -> None:
    state = DeploymentState(app_dir)
    with state.locked():
        release = activate_installed_release(
            state, username, image_manifest=image_manifest, rollback=rollback
        )
    if follow_logs:
        follow_release_logs(release)


def activate_installed_release(
    state: DeploymentState,
    username: str,
    *,
    image_manifest: Path | None,
    rollback: bool,
) -> BetaRelease:
    pending = state.pending()
    base_path = pending.manifest if pending else state.manifest
    settings = RuntimeManifest.read(
        base_path, policy=ImagePolicy.REGISTRY, required_mode=PRIVATE_FILE_MODE
    )
    if pending and pending.phase is AttemptPhase.ACTIVATED:
        release = BetaRelease(
            settings,
            ComposeProject(
                pending.manifest,
                DEFAULT_COMPOSE_PROJECT,
                compose_file=pending.compose_file,
            ),
        )
        release.compose.require_local_docker()
        state.promote(pending)
        print(f"Recovered activated release from {pending.directory}")
        pending = None
        if image_manifest is None:
            return release
    if image_manifest is not None:
        settings = settings.with_images(ReleaseImages.read(image_manifest))
        pending = None
    if pending:
        if rollback and not pending.rollback:
            raise ValueError(
                "pending attempt records forward migration; use --release for an explicit replacement"
            )
        attempt = pending
    else:
        compose_yaml = compose_for_release(settings.images.source_commit)
        attempt = state.prepare(settings, compose_yaml, rollback=rollback)
    release = BetaRelease(
        settings,
        ComposeProject(
            attempt.manifest, DEFAULT_COMPOSE_PROJECT, compose_file=attempt.compose_file
        ),
    )
    release.compose.require_local_docker()
    release.compose.run("config", "--quiet")
    ghcr.login(username)
    release.compose.run("pull")
    state.begin_activation(attempt)
    release.activate(rollback=attempt.rollback)
    activated = state.mark_activated(attempt)
    state.promote(activated)
    print(f"Release activated. Deployment inputs retained in {attempt.directory}")
    return release


def follow_release_logs(release: BetaRelease) -> None:
    try:
        release.compose.run("logs", "--follow", "--tail", str(LOG_TAIL_LINES))
    except KeyboardInterrupt:
        print("Stopped following logs; detached containers keep running.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username", required=True, help="GitHub user with package read access"
    )
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIRECTORY)
    parser.add_argument(
        "--release",
        type=Path,
        help="new or previous published image manifest; explicitly replaces a pending attempt",
    )
    parser.add_argument("--no-logs", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    start(
        args.app_dir,
        args.username,
        image_manifest=args.release,
        follow_logs=not args.no_logs,
        rollback=args.rollback,
    )


if __name__ == "__main__":
    main()
