"""Saved configurations, including retained soft-deleted bots."""

from typing import ClassVar
from uuid import UUID

from sqlalchemy import select

from api.admin.policy import OWNER_DISPLAY, OWNER_FILTER
from api.admin.views import OwnedRecordView, json_value
from api.auth.models import UserRow
from api.bots.models import BotRow


class ConfigurationView(OwnedRecordView, model=BotRow):
    name = "Configuration"
    name_plural = "Configurations"
    column_list: ClassVar = [
        BotRow.id,
        OWNER_DISPLAY,
        BotRow.owner_user_id,
        BotRow.definition_id,
        BotRow.created_at,
        BotRow.updated_at,
        BotRow.deleted_at,
    ]
    column_details_list: ClassVar = [*column_list, BotRow.config]
    column_searchable_list: ClassVar = [BotRow.id]
    column_sortable_list: ClassVar = [
        BotRow.id,
        BotRow.created_at,
        BotRow.updated_at,
        BotRow.deleted_at,
    ]
    column_formatters_detail: ClassVar = {
        **OwnedRecordView.column_formatters_detail,
        BotRow.config: json_value,
    }

    def owner_query(self):
        return select(BotRow.id, UserRow.id, UserRow.email).join(
            UserRow, UserRow.id == BotRow.owner_user_id
        )

    def list_query(self, request):
        stmt = super().list_query(request)
        if value := request.query_params.get(OWNER_FILTER):
            stmt = stmt.where(BotRow.owner_user_id == UUID(value))
        return stmt
