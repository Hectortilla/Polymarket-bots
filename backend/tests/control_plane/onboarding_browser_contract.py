"""Generate only test-case inputs and expectations; no shipped frontend assets."""

import json
from pathlib import Path

from control_plane.onboarding_policy import ONBOARDING_CASES

ONBOARDING_BROWSER_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "frontend/e2e/onboardingContract.fixture.json"
)


def onboarding_browser_contract():
    return {
        "cases": {
            scenario.value: {
                "marketSlug": case.market_slug,
                "expectedFillCount": case.expected_fill_count,
            }
            for scenario, case in ONBOARDING_CASES.items()
        }
    }


if __name__ == "__main__":
    ONBOARDING_BROWSER_CONTRACT_PATH.write_text(
        json.dumps(onboarding_browser_contract(), indent=2) + "\n"
    )
