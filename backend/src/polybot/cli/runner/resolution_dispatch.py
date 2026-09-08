"""Resolution-event dispatch into paper and followed-wallet settlement."""

from ..resolution.settlement import ResolutionSettlementService
from ..streams.contracts import StreamEvent


async def dispatch_resolution(
    event: StreamEvent,
    service: ResolutionSettlementService,
) -> None:
    await service.apply(event.event)
