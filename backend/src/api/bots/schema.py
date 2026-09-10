"""PostgreSQL identifiers for saved bots."""

from enum import StrEnum

BOTS_TABLE_NAME = "bots"


class BotColumn(StrEnum):
    ID = "id"
    DEFINITION_ID = "definition_id"
    CONFIG = "config"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    DELETED_AT = "deleted_at"
