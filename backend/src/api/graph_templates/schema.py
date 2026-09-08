"""PostgreSQL identifiers for editable graph templates."""

from enum import StrEnum


GRAPH_TEMPLATES_TABLE_NAME = "graph_templates"
GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME = "uq_graph_templates_name"


class GraphTemplateColumn(StrEnum):
    ID = "id"
    NAME = "name"
    GRAPH = "graph"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
