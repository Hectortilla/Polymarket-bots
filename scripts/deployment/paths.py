"""Repository source and installed deployment layout."""

from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
SOURCE_DEPLOY_DIRECTORY = Path("deploy")
SOURCE_COMPOSE_PATH = SOURCE_DEPLOY_DIRECTORY / "compose.yaml"
COMPOSE_FILE = REPOSITORY / SOURCE_COMPOSE_PATH
DEFAULT_APP_DIRECTORY = Path.home() / "app"
HOST_COMPOSE_NAME = "docker-compose.yml"
MANIFEST_NAME = ".env"
SECRETS_DIRECTORY_NAME = "secrets"
