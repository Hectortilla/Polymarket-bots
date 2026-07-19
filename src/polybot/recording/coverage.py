"""One conservative resolver for coverage-gap scope and baseline impact."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import CoverageGapPayload, MarketIdentity, MarketMetadataPayload


@dataclass(frozen=True, slots=True)
class CoverageScope:
    condition_ids: frozenset[str]
    market_slugs: frozenset[str]
    token_ids: frozenset[str]

    @classmethod
    def from_gap(
        cls,
        gap: CoverageGapPayload,
        identity: MarketIdentity | None,
    ) -> CoverageScope:
        explicit = cls(
            frozenset(gap.affected_condition_ids),
            frozenset(gap.affected_market_slugs),
            frozenset(gap.affected_token_ids),
        )
        if not explicit.is_global or identity is None:
            return explicit
        return cls(
            frozenset(
                () if identity.condition_id is None else (identity.condition_id,)
            ),
            frozenset(
                () if identity.market_slug is None else (identity.market_slug,)
            ),
            frozenset(() if identity.token_id is None else (identity.token_id,)),
        )

    @property
    def is_global(self) -> bool:
        return not (self.condition_ids or self.market_slugs or self.token_ids)

    def affects(
        self,
        *,
        condition_ids: tuple[str, ...] | None,
        market_slugs: tuple[str, ...] | None,
        token_id: str | None,
    ) -> bool:
        if self.is_global:
            return True
        return all(
            _selection_may_overlap(selected, affected)
            for selected, affected in (
                (condition_ids, self.condition_ids),
                (market_slugs, self.market_slugs),
                (None if token_id is None else (token_id,), self.token_ids),
            )
        )

    def resolved_token_ids(
        self,
        markets: Iterable[MarketMetadataPayload],
    ) -> frozenset[str] | None:
        """Return affected tokens, or ``None`` when every baseline is affected."""
        if self.is_global:
            return None
        tokens = set(self.token_ids)
        for market in markets:
            if (
                market.condition_id in self.condition_ids
                or market.market_slug in self.market_slugs
            ):
                tokens.update(outcome.token_id for outcome in market.outcomes)
        return frozenset(tokens)

    def resolved_condition_ids(
        self,
        markets: Iterable[MarketMetadataPayload],
    ) -> frozenset[str] | None:
        """Return affected conditions, or ``None`` when every market is affected."""
        if self.is_global:
            return None
        conditions = set(self.condition_ids)
        by_slug = {market.market_slug: market.condition_id for market in markets}
        by_token = {
            outcome.token_id: market.condition_id
            for market in markets
            for outcome in market.outcomes
        }
        conditions.update(
            condition_id
            for slug in self.market_slugs
            if (condition_id := by_slug.get(slug)) is not None
        )
        conditions.update(
            condition_id
            for token_id in self.token_ids
            if (condition_id := by_token.get(token_id)) is not None
        )
        return frozenset(conditions)


def _selection_may_overlap(
    selected: tuple[str, ...] | None,
    affected: frozenset[str],
) -> bool:
    if selected is None or not affected:
        return True
    return not set(selected).isdisjoint(affected)
