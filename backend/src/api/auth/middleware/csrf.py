"""Same-origin JSON mutation checks, before authentication or request parsing."""

from fastapi import HTTPException, Request, status

from api.auth.config import AuthSettings
from api.auth.policy import CSRF_FAILED_DETAIL, CSRF_SAFE_METHODS
from api.http.protocol import CONTENT_TYPE_HEADER, JSON_CONTENT_TYPE


def require_same_origin_json(request: Request) -> None:
    if request.method in CSRF_SAFE_METHODS:
        return
    settings = AuthSettings.for_app(request.app)
    content_type = request.headers.get(CONTENT_TYPE_HEADER, "").split(";", 1)[0].lower()
    if (
        request.headers.get("origin") != settings.origin
        or content_type != JSON_CONTENT_TYPE
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, CSRF_FAILED_DETAIL)
