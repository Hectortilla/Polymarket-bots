"""One exact-market scenario resolver for both delivery and runtime ingress."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.framework.config.models import BotConfig

from control_plane.onboarding_policy import ONBOARDING_CASES, OnboardingCase


def onboarding_case(config: BotConfig) -> OnboardingCase | None:
    slugs = config.configured_market_slugs()
    if len(slugs) != 1:
        return None
    return next(
        (case for case in ONBOARDING_CASES.values() if case.market_slug == slugs[0]),
        None,
    )
