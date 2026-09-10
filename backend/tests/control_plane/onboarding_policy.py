"""Test-only cases shared by normalized inputs and generated browser expectations."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

FIXTURE_TICK_SECONDS = 0.1
FIXTURE_RANDOM_SEED = 0


class OnboardingScenario(StrEnum):
    ACTION = "action"
    WAITING = "waiting"


@dataclass(frozen=True)
class OnboardingCase:
    market_slug: str
    ask: Decimal
    expected_fill_count: int


# Prices straddle the catalog entry condition; neither reaches its exit condition.
ONBOARDING_CASES = {
    OnboardingScenario.ACTION: OnboardingCase("onboarding-action", Decimal("0.40"), 1),
    OnboardingScenario.WAITING: OnboardingCase(
        "onboarding-waiting", Decimal("0.55"), 0
    ),
}
