"""Shared read-only SQLAdmin behavior and safe record presentation."""

import json
from typing import ClassVar
from uuid import UUID

from markupsafe import Markup
from sqladmin import ModelView
from sqlalchemy import String, cast, or_
from starlette.exceptions import HTTPException

from api.admin.policy import (
    ADMIN_PAGE_SIZE,
    ADMIN_PAGE_SIZE_OPTIONS,
    ADMIN_SEARCH_MAX_LENGTH,
    BOT_FILTER,
    OWNER_DISPLAY,
    OWNER_FILTER,
    STATUS_FILTER,
    USER_VIEW_ID,
)
from api.auth.models import UserRow
from api.runs.status import RunStatus


def record_link(request, identity, identifier, label):
    return Markup('<a href="{}">{}</a>').format(
        request.url_for("admin:details", identity=identity, pk=str(identifier)), label
    )


def json_value(model, attribute):
    return Markup(
        '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">{}</pre>'
    ).format(json.dumps(getattr(model, attribute), indent=2, ensure_ascii=False))


def owner_link(model, attribute, request):
    owner_id, email = request.state.admin_owners[model.id]
    return record_link(request, USER_VIEW_ID, owner_id, email)


class ReadOnlyView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
    can_import = False
    can_view_details = True
    page_size = ADMIN_PAGE_SIZE
    page_size_options = ADMIN_PAGE_SIZE_OPTIONS
    column_default_sort: ClassVar = [("created_at", True), ("id", True)]
    list_template = "polybot_admin/list.html"
    details_template = "polybot_admin/details.html"
    owner_filter = False
    bot_filter = False
    status_filter = False

    def is_accessible(self, request):
        user = getattr(request.state, "user", None)
        return user is not None and user.is_admin

    async def list(self, request):
        self._validate_query(request)
        return await super().list(request)

    async def get_object_for_details(self, request):
        try:
            UUID(request.path_params["pk"])
        except ValueError:
            raise HTTPException(404, "record not found") from None
        return await super().get_object_for_details(request)

    def _validate_query(self, request):
        for parameter in (OWNER_FILTER, BOT_FILTER):
            value = request.query_params.get(parameter)
            if value:
                try:
                    UUID(value)
                except ValueError:
                    raise HTTPException(400, "invalid record filter") from None
        value = request.query_params.get(STATUS_FILTER)
        if value and value not in RunStatus:
            raise HTTPException(400, "invalid run status")
        sort = request.query_params.get("sortBy")
        if sort and sort not in self._sort_fields:
            raise HTTPException(400, "invalid sort column")
        if len(request.query_params.get("search", "")) > ADMIN_SEARCH_MAX_LENGTH:
            raise HTTPException(400, "search is too long")


class OwnedRecordView(ReadOnlyView):
    owner_filter = True
    column_formatters: ClassVar = {OWNER_DISPLAY: owner_link}
    column_formatters_detail: ClassVar = column_formatters

    def owner_query(self):
        raise NotImplementedError

    async def list(self, request):
        pagination = await super().list(request)
        await self._load_owners(request, [row.id for row in pagination.rows])
        return pagination

    async def get_object_for_details(self, request):
        row = await super().get_object_for_details(request)
        await self._load_owners(request, [] if row is None else [row.id])
        return row

    async def _load_owners(self, request, identifiers):
        async with self.session_maker() as session:
            rows = await session.execute(
                self.owner_query().where(self.model.id.in_(identifiers))
            )
            request.state.admin_owners = {row[0]: (row[1], row[2]) for row in rows}

    def search_query(self, stmt, term):
        owner_matches = (
            self.owner_query()
            .where(UserRow.email.ilike(f"%{term}%"))
            .with_only_columns(self.model.id)
        )
        return stmt.where(
            or_(
                cast(self.model.id, String).ilike(f"%{term}%"),
                self.model.id.in_(owner_matches),
            )
        )
