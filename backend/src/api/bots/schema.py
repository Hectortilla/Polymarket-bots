"""PostgreSQL identifiers for saved bots and graph revisions."""

from enum import StrEnum


BOTS_TABLE_NAME = "bots"
BOT_GRAPH_REVISIONS_TABLE_NAME = "bot_graph_revisions"
BOT_GRAPH_REVISION_NUMBER_CONSTRAINT_NAME = "ck_bot_graph_revision_positive"
BOT_GRAPH_REVISION_SEQUENCE_CONSTRAINT_NAME = "uq_bot_graph_revision_sequence"
BOT_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME = "uq_bot_graph_revision_ownership"


class BotColumn(StrEnum):
    ID = "id"
    DEFINITION_ID = "definition_id"
    CONFIG = "config"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class BotGraphRevisionColumn(StrEnum):
    ID = "id"
    BOT_ID = "bot_id"
    REVISION = "revision"
    GRAPH = "graph"
    CREATED_AT = "created_at"
