"""Deterministic OpenAPI artifact export without server startup."""

import json
from pathlib import Path

from polybot_control_plane.api.app import app


OPENAPI_OUTPUT_PATH = Path(__file__).parents[3] / "openapi" / "control-plane.json"


def main() -> None:
    OPENAPI_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    document = json.dumps(app.openapi(), indent=2, sort_keys=True)
    OPENAPI_OUTPUT_PATH.write_text(f"{document}\n")


if __name__ == "__main__":
    main()
