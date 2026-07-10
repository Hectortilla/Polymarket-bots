from typing import cast

import pytest

from scripts.wallet_analysis import (
    HEDGE_SCORE_THRESHOLD,
    WalletClassificationReason,
    WalletMetrics,
    WalletVerdict,
    classify_wallet_candidate,
)


@pytest.mark.parametrize(
    ("net", "gross", "hedge", "verdict", "reason"),
    (
        (1.0, 1.2, 0.1, WalletVerdict.GOOD, WalletClassificationReason.NET_POSITIVE_DIRECTIONAL_REALIZED),
        (1.0, 1.2, HEDGE_SCORE_THRESHOLD, WalletVerdict.BAD, WalletClassificationReason.HEDGED),
        (-0.1, 0.1, 0.1, WalletVerdict.BAD, WalletClassificationReason.FEE_EATEN),
        (0.0, 0.0, 0.1, WalletVerdict.BAD, WalletClassificationReason.NET_NEGATIVE_OR_FLAT),
    ),
)
def test_wallet_classification_branches(
    net: float,
    gross: float,
    hedge: float,
    verdict: WalletVerdict,
    reason: WalletClassificationReason,
) -> None:
    metrics = cast(
        WalletMetrics,
        {"net_cash": net, "gross_before_fees": gross, "hedge_avg": hedge},
    )
    classification = classify_wallet_candidate(metrics)
    assert classification.verdict is verdict
    assert classification.reason is reason
