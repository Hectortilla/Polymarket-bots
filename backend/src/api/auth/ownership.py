"""The required user-owner field shared by private resource rows."""

from uuid import UUID

from sqlmodel import Field, SQLModel

from api.auth.schema import OWNER_USER_ID_COLUMN, USER_ID_REFERENCE


class UserOwnedRow(SQLModel):
    owner_user_id: UUID = Field(
        foreign_key=USER_ID_REFERENCE,
        nullable=False,
        index=True,
        sa_column_kwargs={"name": OWNER_USER_ID_COLUMN},
    )
