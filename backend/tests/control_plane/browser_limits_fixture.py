"""Explicit auth-budget reset control for isolated acceptance launchers only."""

from fastapi.responses import JSONResponse

from control_plane.disposable_services import clear_auth_attempts

CLEAR_LIMITS_PATH = "/api/v1/__test/account-limits"


def install_browser_limit_control(app):
    @app.middleware("http")
    async def test_limits(request, call_next):
        if request.url.path == CLEAR_LIMITS_PATH and request.method == "POST":
            await clear_auth_attempts(app.state.redis)
            return JSONResponse({"cleared": True})
        return await call_next(request)
