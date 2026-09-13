"""Read active and pending release inputs once at the persistence boundary."""

from dataclasses import dataclass, replace

from scripts.deployment.attempt import DeploymentAttempt
from scripts.deployment.bundle.installation import InstalledBundle
from scripts.deployment.dotenv import read_values
from scripts.deployment.images import ImagePolicy
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import RUNTIME_CONFIGURATION_NAME
from scripts.deployment.state import DeploymentState
from scripts.private_files import PRIVATE_FILE_MODE, read_regular


@dataclass(frozen=True)
class ActivationSelection:
    settings: RuntimeManifest
    retained: DeploymentAttempt | None
    already_active: bool

    @classmethod
    def read(
        cls, state: DeploymentState, bundle: InstalledBundle, *, rollback: bool
    ) -> "ActivationSelection":
        pending = state.pending()
        selected_manifest = pending.manifest if pending else state.manifest
        retained_settings = (
            RuntimeManifest.read(
                selected_manifest,
                policy=ImagePolicy.REGISTRY,
                required_mode=PRIVATE_FILE_MODE,
            )
            if selected_manifest.exists()
            else None
        )
        runtime_values = (
            read_values(
                state.directory / RUNTIME_CONFIGURATION_NAME,
                required_mode=PRIVATE_FILE_MODE,
            )
            if not pending
            else {}
        )
        if retained_settings is None and rollback:
            raise ValueError("cannot roll back a fresh installation")
        if retained_settings is not None:
            settings = retained_settings.with_images(bundle.release.images)
            settings = RuntimeManifest.from_values(
                {**settings.to_values(), **runtime_values}, policy=ImagePolicy.REGISTRY
            )
        else:
            settings = RuntimeManifest.from_values(
                {**runtime_values, **bundle.release.images.to_values()},
                policy=ImagePolicy.REGISTRY,
            )
        settings = replace(settings, bundle_directory=bundle.directory)
        retained = None
        if (
            pending
            and retained_settings is not None
            and retained_settings.images == bundle.release.images
        ):
            if pending.rollback != rollback:
                raise ValueError(
                    "pending attempt operation differs; retry its recorded operation"
                )
            if (
                retained_settings != settings
                or read_regular(pending.compose_file) != bundle.compose_yaml
            ):
                raise ValueError("pending attempt differs from the selected bundle")
            retained = pending
        already_active = (
            not pending
            and bundle.is_current(state.directory)
            and retained_settings == settings
            and read_regular(state.compose_file) == bundle.compose_yaml
        )
        return cls(settings, retained, already_active)
