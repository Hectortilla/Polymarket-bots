"""Project closed response-object fields from the exported OpenAPI contract."""

import json
from pathlib import Path

OPENAPI_PATH = (
    Path(__file__).resolve().parents[2] / "contracts/openapi/control-plane.json"
)


def response_field_contract() -> dict[str, object]:
    schemas = json.loads(OPENAPI_PATH.read_text())["components"]["schemas"]
    models = {
        name: list(schema["properties"])
        for name, schema in schemas.items()
        if schema.get("additionalProperties") is False
        and (
            name.endswith(("Payload", "Event"))
            or name in {"GraphValueRead", "RunEventPage"}
        )
    }
    return {
        "models": models,
        "durable": _event_fields(schemas, "PersistedDurableEvent"),
        "live": _event_fields(schemas, "LiveRunEvent"),
    }


def _event_fields(schemas: dict, union: str) -> dict[str, list[str]]:
    return {
        kind: list(schemas[reference.rsplit("/", 1)[-1]]["properties"])
        for kind, reference in schemas[union]["discriminator"]["mapping"].items()
    }
