"""Secret-safe HTTP failure and admission accounting at the response boundary."""

import asyncio

from fastapi import status
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.operations.observations.contracts import (
    FailureObservation,
    HttpObservation,
    Observation,
)
from api.operations.observations.sink import OPERATION_LOG
from api.operations.telemetry.counters import ObservationCounters

ADMISSION_REJECTION_SCOPE_KEY = "operation_admission_rejected"
HTTP_EXECUTION_FAILURE_DETAIL = "request execution failed"


class OperationalHttpMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        error_recorded = False

        async def observe(message: Message) -> None:
            nonlocal error_recorded
            if message["type"] == "http.response.start":
                response_status = message["status"]
                if (
                    response_status >= status.HTTP_500_INTERNAL_SERVER_ERROR
                    or self._is_admission_rejection(scope, response_status)
                ):
                    await self._record_http_operational_event(scope, response_status)
                    error_recorded = True
            await send(message)

        try:
            await self.app(scope, receive, observe)
        except Exception:
            # Errors after SSE headers are still errors, even though status is immutable.
            if not error_recorded:
                await self._record_http_operational_event(
                    scope, status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            raise RuntimeError(HTTP_EXECUTION_FAILURE_DETAIL) from None

    async def _record_http_operational_event(
        self, scope: Scope, response_status: int
    ) -> None:
        admission_rejected = self._is_admission_rejection(scope, response_status)
        event = (
            Observation.ADMISSION_REJECTION
            if admission_rejected
            else Observation.HTTP_ERROR
        )
        OPERATION_LOG.emit(HttpObservation(event, response_status))
        try:
            async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                await ObservationCounters(scope["app"].state.redis).increment(event)
        except Exception:
            OPERATION_LOG.emit(FailureObservation(Observation.TELEMETRY_UNAVAILABLE))

    @staticmethod
    def _is_admission_rejection(scope: Scope, response_status: int) -> bool:
        return response_status == status.HTTP_429_TOO_MANY_REQUESTS or scope.get(
            ADMISSION_REJECTION_SCOPE_KEY, False
        )
