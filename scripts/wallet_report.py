from __future__ import annotations

from collections.abc import Mapping

from scripts.terminal import color_enabled
from scripts.wallet_analysis import HEDGE_SCORE_THRESHOLD, classify_wallet_candidate, market_trade_share
from scripts.wallet_analysis import WalletMetrics

GOOD_VERDICT = "Good for the trader"
BAD_VERDICT = "Bad"


def _color(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if color_enabled() else text


def good(text: str) -> str:
    return _color("32", text)


def bad(text: str) -> str:
    return _color("31", text)


def warn(text: str) -> str:
    return _color("33", text)


def dim(text: str) -> str:
    return _color("90", text)


def heading(text: str) -> str:
    return _color("1;36", text)


def signed(value: float) -> str:
    rendered = f"{value:+,.2f}"
    return good(rendered) if value > 0.005 else bad(rendered) if value < -0.005 else dim(rendered)


def verdict_label(is_good: bool) -> str:
    return good(GOOD_VERDICT) if is_good else bad(BAD_VERDICT)


def print_wallet_report(
    metrics: WalletMetrics,
    wallet: str,
    *,
    target_slug: str | None = None,
    target_condition_id: str | None = None,
) -> None:
    if int(metrics["n_items"]) == 0:
        print(warn(f"{wallet}: no activity found."))
        return
    classification = classify_wallet_candidate(metrics)
    market_share = market_trade_share(
        metrics["activity"],
        target_slug=target_slug,
        target_condition_id=target_condition_id,
    )
    print(heading(f"\nWALLET {wallet}"))
    print(f"activity items : {metrics['n_items']} ({metrics['n_trades']} trades)")
    print(f"markets touched: {metrics['n_markets']}")
    print(f"net cash       : {signed(float(metrics['net_cash']))} USDC")
    print(f"fees           : {float(metrics['fees']):,.2f} USDC")
    print(
        f"hedge score    : {float(metrics['hedge_avg']):.2f} "
        f"(mirage >= {HEDGE_SCORE_THRESHOLD:.2f})"
    )
    if target_slug or target_condition_id:
        print(f"target share   : {market_share:.2f}%")
    print(
        f"VERDICT        : {verdict_label(classification.is_good)} "
        f"({classification.explanation})"
    )
