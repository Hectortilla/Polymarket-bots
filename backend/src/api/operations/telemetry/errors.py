"""Malformed shared telemetry is distinct from a transport outage."""


class TelemetryDataError(ValueError):
    def __init__(self) -> None:
        super().__init__("operational telemetry is malformed")
