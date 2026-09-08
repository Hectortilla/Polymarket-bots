from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
)

from api.catalog.graphs._fields import DiscoveredGraphField
from api.catalog.graphs._triggers import (
    DiscoveredGraphPayload,
    DiscoveredGraphTrigger,
)
from api.catalog.graphs.preview_samples import (
    PREVIEW_SAMPLE_TIME_MS,
    sample_payload,
)
from api.catalog.graphs.types import (
    GraphFieldPath,
    GraphHandleId,
    GraphHookName,
)
from api.catalog.graphs.values import (
    GRAPH_CONTEXT_HANDLE_ID,
    GRAPH_CONTEXT_TYPE_NAME,
    GraphNodeType,
    GraphScalarType,
)


class GraphFieldDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: GraphFieldPath
    handle_id: GraphHandleId
    display_name: str
    value_type: str
    scalar_type: GraphScalarType | None
    nullable: bool
    collection: bool
    value_schema: dict[str, object]

    @classmethod
    def from_discovered(
        cls,
        payload_type_name: str,
        field: DiscoveredGraphField,
    ) -> Self:
        path = GraphFieldPath(segments=field.path)
        return cls(
            path=path,
            handle_id=path.handle_id,
            display_name=f"{payload_type_name}.{path.dotted}",
            value_type=field.value_type,
            scalar_type=field.scalar_type,
            nullable=field.nullable,
            collection=field.collection,
            value_schema=dict(field.value_schema),
        )


class GraphPayloadDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type_name: str
    fields: tuple[GraphFieldDescriptor, ...]

    @classmethod
    def from_discovered(cls, payload: DiscoveredGraphPayload) -> Self:
        return cls(
            type_name=payload.type_name,
            fields=tuple(
                GraphFieldDescriptor.from_discovered(payload.type_name, field)
                for field in payload.fields
            ),
        )

    def field_for_path(self, path: GraphFieldPath) -> GraphFieldDescriptor | None:
        return next((field for field in self.fields if field.path == path), None)


class GraphTriggerDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_type: Literal[GraphNodeType.TRIGGER] = GraphNodeType.TRIGGER
    hook_name: GraphHookName
    context_handle_id: Literal[GRAPH_CONTEXT_HANDLE_ID]
    context_type_name: Literal[GRAPH_CONTEXT_TYPE_NAME]
    payload: GraphPayloadDescriptor | None = None
    sample_payload: dict[str, Any] | None = None
    sample_time_ms: int = PREVIEW_SAMPLE_TIME_MS

    @classmethod
    def from_discovered(cls, trigger: DiscoveredGraphTrigger) -> Self:
        return cls(
            hook_name=trigger.hook_name,
            sample_payload=sample_payload(trigger.hook_name),
            context_handle_id=GRAPH_CONTEXT_HANDLE_ID,
            context_type_name=GRAPH_CONTEXT_TYPE_NAME,
            payload=(
                None
                if trigger.payload is None
                else GraphPayloadDescriptor.from_discovered(trigger.payload)
            ),
        )
