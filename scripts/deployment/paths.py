"""Repository source and installed deployment layout."""

from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
SOURCE_DEPLOY_DIRECTORY = Path("deploy")
SOURCE_COMPOSE_PATH = SOURCE_DEPLOY_DIRECTORY / "compose.yaml"
COMPOSE_FILE = REPOSITORY / SOURCE_COMPOSE_PATH
DEFAULT_APP_DIRECTORY = Path("/srv/polybot")
HOST_COMPOSE_NAME = "docker-compose.yml"
MANIFEST_NAME = ".env"
SECRETS_DIRECTORY_NAME = "secrets"


RUNTIME_CONFIGURATION_NAME = "runtime.env"
OPERATIONS_CONFIGURATION_NAME = "operations.json"
STAGING_DIRECTORY_NAME = "staging"
RELEASES_DIRECTORY_NAME = "bundles"
CURRENT_RELEASE_NAME = "current"
NEXT_RELEASE_NAME = ".current-next"
REGISTRY_AUTH_DIRECTORY_NAME = "registry"
CI_INPUTS_FILENAME = "deploy-inputs.json"
