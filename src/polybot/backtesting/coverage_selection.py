"""Coverage-gap scope matching against selected replay markets."""

from __future__ import annotations

from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.records import CoverageGapRecord
from polybot.recording.coverage import CoverageScope


def gaps_affecting_markets(
    records: tuple[CoverageGapRecord, ...],
    markets: tuple[MarketMetadataPayload, ...],
) -> tuple[CoverageGapRecord, ...]:
    """Resolve conservative recorded scopes against concrete selected markets."""

    selected_condition_ids = {market.condition_id for market in markets}
    return tuple(
        record
        for record in records
        if _gap_affects_selected_markets(
            record,
            markets,
            selected_condition_ids,
        )
    )


def _gap_affects_selected_markets(
    record: CoverageGapRecord,
    markets: tuple[MarketMetadataPayload, ...],
    selected_condition_ids: set[str],
) -> bool:
    affected_condition_ids = CoverageScope.from_gap(
        record.gap,
        record.identity,
    ).resolved_condition_ids(markets)
    return (
        affected_condition_ids is None
        or not selected_condition_ids.isdisjoint(affected_condition_ids)
    )
