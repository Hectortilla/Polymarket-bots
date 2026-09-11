"""A selected durable event and its server-assigned presentation channel."""

from dataclasses import dataclass

from api.events.contracts import PersistedDurableEvent


@dataclass(frozen=True, slots=True)
class EventDelivery:
    event: PersistedDurableEvent
    dashboard_only: bool
