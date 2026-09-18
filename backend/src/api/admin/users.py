"""Explicitly allowlisted user inspection."""

from typing import ClassVar

from api.admin.views import ReadOnlyView
from api.auth.models import UserRow


class UserView(ReadOnlyView, model=UserRow):
    name = "User"
    name_plural = "Users"
    column_list: ClassVar = [
        UserRow.id,
        UserRow.email,
        UserRow.created_at,
        UserRow.email_verified_at,
        UserRow.suspended_at,
        UserRow.restore_quarantined_at,
        UserRow.is_admin,
    ]
    column_details_list: ClassVar = [*column_list, UserRow.verification_required]
    column_searchable_list: ClassVar = [UserRow.email, UserRow.id]
    column_sortable_list: ClassVar = [UserRow.email, UserRow.created_at, UserRow.id]
