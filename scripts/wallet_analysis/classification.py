"""Wallet-candidate classification rules."""

from .contracts import (
    GROSS_BEFORE_FEES_METRIC,
    HEDGE_AVERAGE_METRIC,
    NET_CASH_METRIC,
    WalletClassification,
    WalletClassificationReason,
    WalletMetrics,
    WalletVerdict,
)

HEDGE_SCORE_THRESHOLD = 0.80


def classify_wallet_candidate(wallet_metrics: WalletMetrics) -> WalletClassification:
    net_cash = wallet_metrics[NET_CASH_METRIC]
    fee_eaten = wallet_metrics[GROSS_BEFORE_FEES_METRIC] > 0 and net_cash < 0
    hedged = wallet_metrics[HEDGE_AVERAGE_METRIC] >= HEDGE_SCORE_THRESHOLD
    if net_cash > 0 and not hedged and not fee_eaten:
        return WalletClassification(
            WalletVerdict.GOOD,
            WalletClassificationReason.NET_POSITIVE_DIRECTIONAL_REALIZED,
            "net positive after fees, directional, realized",
        )
    if hedged:
        return WalletClassification(
            WalletVerdict.BAD,
            WalletClassificationReason.HEDGED,
            "hedged both sides (volume/airdrop farm shape)",
        )
    if fee_eaten:
        return WalletClassification(
            WalletVerdict.BAD,
            WalletClassificationReason.FEE_EATEN,
            "edge eaten by fees -> net loser",
        )
    if net_cash <= 0:
        return WalletClassification(
            WalletVerdict.BAD,
            WalletClassificationReason.NET_NEGATIVE_OR_FLAT,
            "net negative/flat after fees",
        )
    return WalletClassification(
        WalletVerdict.BAD,
        WalletClassificationReason.INCONCLUSIVE,
        "inconclusive",
    )
