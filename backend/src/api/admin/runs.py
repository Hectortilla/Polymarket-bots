"""Run metadata and immutable configuration snapshots."""

from typing import ClassVar
from uuid import UUID

from sqlalchemy import select

from api.admin.policy import (
    BOT_FILTER,
    CONFIGURATION_VIEW_ID,
    OWNER_DISPLAY,
    OWNER_FILTER,
    STATUS_FILTER,
)
from api.admin.views import OwnedRecordView, json_value, record_link
from api.auth.models import UserRow
from api.bots.models import BotRow
from api.runs.models import RunRow


def bot_link(model, attribute, request):
    return record_link(request, CONFIGURATION_VIEW_ID, model.bot_id, model.bot_id)


class RunView(OwnedRecordView, model=RunRow):
    name = "Run"
    name_plural = "Runs"
    bot_filter = True
    status_filter = True
    column_list: ClassVar = [
        RunRow.id,
        OWNER_DISPLAY,
        RunRow.bot_id,
        RunRow.status,
        RunRow.created_at,
        RunRow.started_at,
        RunRow.ended_at,
    ]
    column_details_list: ClassVar = [
        *column_list,
        RunRow.definition_id,
        RunRow.heartbeat_at,
        RunRow.failure_detail,
        RunRow.history_expired_at,
        RunRow.config_snapshot,
    ]
    column_searchable_list: ClassVar = [RunRow.id]
    column_sortable_list: ClassVar = [
        RunRow.id,
        RunRow.created_at,
        RunRow.started_at,
        RunRow.ended_at,
        RunRow.status,
    ]
    column_formatters: ClassVar = {
        **OwnedRecordView.column_formatters,
        RunRow.bot_id: bot_link,
    }
    column_formatters_detail: ClassVar = {
        **column_formatters,
        RunRow.config_snapshot: json_value,
    }

    def owner_query(self):
        return (
            select(RunRow.id, UserRow.id, UserRow.email)
            .join(BotRow, BotRow.id == RunRow.bot_id)
            .join(UserRow, UserRow.id == BotRow.owner_user_id)
        )

    def list_query(self, request):
        stmt = super().list_query(request)
        if value := request.query_params.get(OWNER_FILTER):
            stmt = stmt.join(BotRow, BotRow.id == RunRow.bot_id).where(
                BotRow.owner_user_id == UUID(value)
            )
        if value := request.query_params.get(BOT_FILTER):
            stmt = stmt.where(RunRow.bot_id == UUID(value))
        if value := request.query_params.get(STATUS_FILTER):
            stmt = stmt.where(RunRow.status == value)
        return stmt
