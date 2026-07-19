"""Command implementation for scanning BTC five-minute market wallets."""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from polymarket.errors import PolymarketError

from scripts.paths import BAD_FILE, GOOD_FILE
from scripts.polymarket_wallet_api import (
    fetch_all_activity,
    fetch_market_positions,
    fetch_positions,
    gamma_condition_id,
)
from scripts.wallet_analysis.classification import classify_wallet_candidate
from scripts.wallet_analysis.market_metrics import market_trade_share
from scripts.wallet_analysis.metrics import compute_metrics
from scripts.terminal import bad, dim, heading, warn
from scripts.wallet_report import print_wallet_report, verdict_label
from scripts.wallet_results import append_wallet_result, load_seen_wallets
from scripts.wallets_finder.records import result_note, unique_holders
from scripts.wallets_finder.windows import (
    BUCKET_SECONDS,
    current_bucket_start,
    seconds_to_next_window,
    slug_for_start,
    window_label,
)


def resolve_target(
    back: int = 1,
    slug_override: str | None = None,
) -> tuple[str, str | None]:
    if slug_override:
        condition_id, _ = gamma_condition_id(slug_override)
        return slug_override, condition_id
    bucket_start = current_bucket_start()
    slug = slug_for_start(bucket_start - BUCKET_SECONDS * back)
    for offset in range(back, back + 4):
        slug = slug_for_start(bucket_start - BUCKET_SECONDS * offset)
        condition_id, _ = gamma_condition_id(slug)
        if condition_id:
            return slug, condition_id
    return slug, None


def scan_market(
    slug: str,
    condition_id: str,
    limit: int,
    verbose: bool,
    pause: float = 0.4,
) -> int:
    print(heading(f"\n[{_utcnow()}] Market: {slug}"))
    print(f"  window   : {window_label(slug)}")
    print(f"  condition: {condition_id}")
    try:
        positions = fetch_market_positions(condition_id)
    except PolymarketError as error:
        print(bad(f"  Failed to fetch market positions: {error}"))
        return 0
    processed = load_seen_wallets(GOOD_FILE) | load_seen_wallets(BAD_FILE)
    completed = 0
    for wallet, holder_position in unique_holders(positions):
        if limit and completed >= limit:
            break
        if wallet in processed:
            continue
        try:
            activity, truncated = fetch_all_activity(wallet)
            wallet_positions = fetch_positions(wallet)
        except PolymarketError as error:
            print(warn(f"error {wallet}: {error} (skipped)"))
            continue
        metrics = compute_metrics(activity, wallet_positions, truncated)
        classification = classify_wallet_candidate(metrics)
        market_share = market_trade_share(
            activity,
            target_slug=slug,
            target_condition_id=condition_id,
        )
        density = (
            float(metrics["trade_count"])
            / float(metrics["activity_span_hours"])
            * 24
        )
        append_wallet_result(
            GOOD_FILE if classification.is_good else BAD_FILE,
            wallet,
            result_note(
                classification.verdict,
                metrics,
                market_share,
                density,
                classification.reason,
            ),
        )
        processed.add(wallet)
        completed += 1
        size = float(holder_position.get("size") or 0)
        print(
            f"{wallet} size={size:,.0f} "
            f"net={float(metrics['net_cash']):+,.2f} "
            f"hedge={metrics['hedge_avg']:.2f} -> "
            f"{verdict_label(classification.is_good)}"
        )
        if verbose:
            print_wallet_report(
                metrics,
                wallet,
                target_slug=slug,
                target_condition_id=condition_id,
            )
        time.sleep(pause)
    print(dim(f"  window done: {completed} new wallet(s) classified."))
    return completed


def run_scan(
    back: int,
    limit: int,
    verbose: bool,
    slug_override: str | None,
) -> None:
    slug, condition_id = resolve_target(back, slug_override)
    if condition_id is None:
        print(bad(f"Could not resolve a condition ID for {slug}."))
        return
    scan_market(slug, condition_id, limit, verbose)


def run_forever(limit: int, verbose: bool, buffer: int = 10) -> None:
    print(heading("Watching BTC Up/Down 5m. Ctrl-C to stop."))
    last_slug = None
    try:
        while True:
            slug, condition_id = resolve_target(back=1)
            if condition_id and slug != last_slug:
                scan_market(slug, condition_id, limit, verbose)
                last_slug = slug
            elif not condition_id:
                print(warn(f"[{_utcnow()}] could not resolve {slug}"))
            time.sleep(seconds_to_next_window(buffer))
    except KeyboardInterrupt:
        print("stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge Polymarket BTC-5m wallets.")
    parser.add_argument("--wallet")
    parser.add_argument("--slug")
    parser.add_argument("--back", type=int, default=1)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--buffer", type=int, default=10)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.wallet:
        activity, truncated = fetch_all_activity(args.wallet)
        print_wallet_report(
            compute_metrics(activity, fetch_positions(args.wallet), truncated),
            args.wallet,
        )
    elif args.loop:
        run_forever(args.limit, args.verbose, args.buffer)
    else:
        run_scan(args.back, args.limit, args.verbose, args.slug)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")
