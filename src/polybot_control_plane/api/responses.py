"""Reusable OpenAPI response declarations for HTTP error boundaries."""

from fastapi import status

from polybot_control_plane.api.contracts import ErrorResponse

NOT_FOUND_RESPONSE = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
}
CONFLICT_RESPONSE = {
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
}
SERVICE_UNAVAILABLE_RESPONSE = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
}
NOT_FOUND_AND_CONFLICT_RESPONSES = {
    **NOT_FOUND_RESPONSE,
    **CONFLICT_RESPONSE,
}
