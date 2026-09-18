"""Mount the explicitly registered inspection views against application sessions."""

from pathlib import Path

from sqladmin import Admin
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.admin.authentication import ExistingSessionAuthentication
from api.admin.configurations import ConfigurationView
from api.admin.policy import (
    ADMIN_PATH,
    BOT_FILTER,
    CONFIGURATION_VIEW_ID,
    OWNER_FILTER,
    RUN_VIEW_ID,
    STATUS_FILTER,
    USER_VIEW_ID,
)
from api.admin.runs import RunView
from api.admin.users import UserView
from api.auth.policy import LOGOUT_PATH
from api.http.routes.paths import api_route_path
from api.runs.status import RunStatus

READ_ONLY_ROUTE_NAMES = frozenset(
    {"statics", "index", "list", "details", "login", "logout"}
)


def install_admin(app) -> None:
    if hasattr(app.state, "admin"):
        return
    admin = Admin(
        app,
        # SQLAdmin changes autoflush on its factory; preserve application write semantics.
        session_maker=async_sessionmaker(**app.state.session_factory.kw),
        base_url=ADMIN_PATH,
        title="Polybot Admin",
        templates_dir=str(Path(__file__).parent / "templates"),
        authentication_backend=ExistingSessionAuthentication(),
    )
    for view in (UserView, ConfigurationView, RunView):
        admin.add_view(view)
    # Keep even authenticated callers away from generic exports, forms and helpers.
    admin.admin.router.routes = [
        route
        for route in admin.admin.router.routes
        if route.name in READ_ONLY_ROUTE_NAMES
    ]
    admin.templates.env.globals.update(
        admin_logout_path=api_route_path(LOGOUT_PATH),
        owner_filter=OWNER_FILTER,
        bot_filter=BOT_FILTER,
        status_filter=STATUS_FILTER,
        run_statuses=tuple(RunStatus),
        user_view_id=USER_VIEW_ID,
        configuration_view_id=CONFIGURATION_VIEW_ID,
        run_view_id=RUN_VIEW_ID,
    )
    app.state.admin = admin
