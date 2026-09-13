"""Validate a persisted promotion candidate before changing active pointers."""

from dataclasses import dataclass
from pathlib import Path

from scripts.deployment.attempt import DeploymentAttempt
from scripts.deployment.bundle.installation import InstalledBundle
from scripts.deployment.images import ImagePolicy
from scripts.deployment.manifest import RuntimeManifest
from scripts.private_files import PRIVATE_FILE_MODE, read_regular


@dataclass(frozen=True)
class PromotionCandidate:
    bundle_directory: Path
    manifest_values: bytes
    compose_yaml: bytes

    @classmethod
    def read(
        cls, attempt: DeploymentAttempt, app_directory: Path
    ) -> "PromotionCandidate":
        settings = RuntimeManifest.read(
            attempt.manifest,
            policy=ImagePolicy.REGISTRY,
            required_mode=PRIVATE_FILE_MODE,
        )
        bundle = InstalledBundle.read(
            settings.require_bundle_directory(), app_directory
        )
        bundle.require_images(settings.images)
        compose_yaml = read_regular(attempt.compose_file)
        if compose_yaml != bundle.compose_yaml:
            raise ValueError("candidate Compose configuration differs from its bundle")
        return cls(
            bundle.directory,
            read_regular(attempt.manifest, required_mode=PRIVATE_FILE_MODE),
            compose_yaml,
        )
