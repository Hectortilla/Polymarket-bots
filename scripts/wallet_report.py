from __future__ import annotations

from collections.abc import Mapping

from scripts.terminal import bad, dim, good, heading, warn
from scripts.wallet_analysis.classification import (
    HEDGE_SCORE_THRESHOLD,
    classify_wallet_candidate,
)
from scripts.wallet_analysis.contracts import (
    ACTIVITY_COUNT_METRIC,
    ACTIVITY_METRIC,
    FEES_METRIC,
    HEDGE_AVERAGE_METRIC,
    MARKET_COUNT_METRIC,
    NET_CASH_METRIC,
    PNL_SIGNIFICANCE_THRESHOLD,
    TRADE_COUNT_METRIC,
    WalletMetrics,
)
from scripts.wallet_analysis.market_metrics import market_trade_share

GOOD_VERDICT = "Good for the trader"
BAD_VERDICT = "Bad"


def format_signed_net_cash(value: float) -> str:
    rendered = f"{value:+,.2f}"
    return (
        good(rendered)
        if value > PNL_SIGNIFICANCE_THRESHOLD
        else bad(rendered)
        if value < -PNL_SIGNIFICANCE_THRESHOLD
        else dim(rendered)
    )


def verdict_label(is_good: bool) -> str:
    return good(GOOD_VERDICT) if is_good else bad(BAD_VERDICT)


def print_wallet_report(
    metrics: WalletMetrics,
    wallet: str,
    *,
    target_slug: str | None = None,
    target_condition_id: str | None = None,
) -> None:
    if int(metrics[ACTIVITY_COUNT_METRIC]) == 0:
        print(warn(f"{wallet}: no activity found."))
        return
    classification = classify_wallet_candidate(metrics)
    market_share = market_trade_share(
        metrics[ACTIVITY_METRIC],
        target_slug=target_slug,
        target_condition_id=target_condition_id,
    )
    print(heading(f"\nWALLET {wallet}"))
    print(
        f"activity items : {metrics[ACTIVITY_COUNT_METRIC]} "
        f"({metrics[TRADE_COUNT_METRIC]} trades)"
    )
    print(f"markets touched: {metrics[MARKET_COUNT_METRIC]}")
    print(
        "net cash       : "
        f"{format_signed_net_cash(float(metrics[NET_CASH_METRIC]))} USDC"
    )
    print(f"fees           : {float(metrics[FEES_METRIC]):,.2f} USDC")
    print(
        f"hedge score    : {float(metrics[HEDGE_AVERAGE_METRIC]):.2f} "
        f"(mirage >= {HEDGE_SCORE_THRESHOLD:.2f})"
    )
    if target_slug or target_condition_id:
        print(f"target share   : {market_share:.2f}%")
    print(
        f"VERDICT        : {verdict_label(classification.is_good)} "
        f"({classification.explanation})"
    )
