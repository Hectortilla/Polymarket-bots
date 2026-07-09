#!/usr/bin/env python3
"""Scan the holders of the just-closed 'BTC Up or Down 5m' market and judge
each wallet: real edge, or mirage?

Flow (default, no args):
  1. Infer the slug of the LAST finished 5-min market from the current time.
     Slug = btc-updown-5m-<unix_start>, where unix_start is the window's start
     in UTC and always a multiple of 300. The just-closed window's start is
     (now // 300)*300 - 300.
  2. Resolve slug -> conditionId via the Gamma API.
  3. Pull that market's positions (biggest holders first).
  4. For each wallet, biggest down: skip if already seen, else run the analyzer
     and classify it into good_wallets.txt or bad_wallets.txt.

Single-wallet mode:  python3 pm_analyze.py --wallet 0xABC...   (prints full report)
Scan mode:           python3 pm_analyze.py [--back N] [--limit N] [--verbose]

No API key needed -- all endpoints are public, read-only.
"""

from __future__ import annotations

import os
import sys
import time
import argparse
import requests
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
GAMMA_MARKETS_PATH = "/markets"

RESULTS_DIR = Path(__file__).resolve().parent / "results"
GOOD_FILE = RESULTS_DIR / "good_wallets.txt"
BAD_FILE = RESULTS_DIR / "bad_wallets.txt"

# thresholds for the good/bad call
HEDGE_MIRAGE = 0.80    # >= this = delta-neutral volume farm
MAX_OFFSET = 3000      # Polymarket /activity historical offset cap

# --------------------------------------------------------------------------- #
# Color: green=good for trader, red=bad, yellow=caution/cost, gray=neutral.
# Auto-off when piped to a file or NO_COLOR is set.
# --------------------------------------------------------------------------- #
_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _w(code, s):
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def GOOD(s): return _w("32", s)
def BAD(s):  return _w("31", s)
def WARN(s): return _w("33", s)
def DIM(s):  return _w("90", s)
def HEAD(s): return _w("1;36", s)
def BOLD(s): return _w("1", s)


def sgn(x, fmt="{:+,.2f}"):
    """Format then color: green if it helps the trader (>0), red if it hurts."""
    t = fmt.format(x)
    return GOOD(t) if x > 0.005 else BAD(t) if x < -0.005 else DIM(t)


def hedgecol(h, fmt="{:.2f}"):
    t = fmt.format(h)
    return BAD(t) if h >= HEDGE_MIRAGE else GOOD(t) if h < 0.60 else WARN(t)


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def fetch_all_activity(wallet, max_items=None):
    """Recent activity, newest first.

    API caps offset at 3000, so this is the ~3000-3500 most-recent items.
    Each row is enriched with `market_slug` when the market can be resolved.
    Returns (items, truncated).
    """
    out, offset, page = [], 0, 500
    truncated = False
    while True:
        if offset > MAX_OFFSET or (max_items and len(out) >= max_items):
            truncated = truncated or offset > MAX_OFFSET
            break
        resp = requests.get(
            f"{BASE}/activity",
            params={"user": wallet, "limit": page, "offset": offset,
                    "sortBy": "TIMESTAMP", "sortDirection": "DESC"},
            timeout=30,
        )
        if resp.status_code == 400:      # offset cap backstop
            truncated = True
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return _enrich_activity_with_market_slug(out), truncated


def _market_slug_from_gamma(condition_id, cache):
    if not condition_id:
        return None
    if condition_id in cache:
        return cache[condition_id]

    try:
        resp = requests.get(
            f"{GAMMA}{GAMMA_MARKETS_PATH}",
            params={"condition_ids": condition_id, "limit": 1},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException:
        cache[condition_id] = None
        return None

    if isinstance(payload, list):
        market = payload[0] if payload else None
    elif isinstance(payload, dict):
        markets = payload.get("markets")
        if isinstance(markets, list):
            market = markets[0] if markets else None
        else:
            market = payload
    else:
        market = None

    slug = None
    if isinstance(market, dict):
        slug = market.get("slug")
    cache[condition_id] = slug
    return slug


def _enrich_activity_with_market_slug(activity):
    slug_cache = {}
    enriched = []
    for item in activity:
        row = dict(item)
        slug = row.get("market_slug") or row.get("slug")
        if slug is None:
            slug = _market_slug_from_gamma(row.get("conditionId"), slug_cache)
        if slug is not None:
            row["market_slug"] = slug
            row.setdefault("slug", slug)
        enriched.append(row)
    return enriched


def fetch_positions(wallet):
    """A wallet's current open positions (unrealized value + Polymarket's P&L)."""
    try:
        resp = requests.get(
            f"{BASE}/positions",
            params={"user": wallet, "sizeThreshold": 0.1, "limit": 500},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return []


def gamma_condition_id(slug):
    """Resolve a market slug -> conditionId (and closed flag) via Gamma."""
    try:
        resp = requests.get(f"{GAMMA}/events", params={"slug": slug}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None, None
    if not data:
        return None, None
    m = data[0] if isinstance(data, list) else data
    return m.get("markets", [{}])[0].get("conditionId"), m.get("closed")


def fetch_market_positions(condition_id, limit=500):
    """All holders of a market, biggest position first."""
    resp = requests.get(
        f"{BASE}/v1/market-positions",
        params={"market": condition_id, "status": "ALL",
                "sortBy": "TOKENS", "sortDirection": "DESC",
                "limit": min(limit, 500)},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()[0]["positions"]


# --------------------------------------------------------------------------- #
# Slug inference from time
# --------------------------------------------------------------------------- #
def current_bucket_start(now=None):
    now = int(now if now is not None else time.time())
    return now - (now % 300)


def slug_for_start(start_ts):
    return f"btc-updown-5m-{start_ts}"


def resolve_target(back=1, slug_override=None):
    """Return (slug, conditionId) for the market to scan. Defaults to the
    just-closed window; if Gamma hasn't indexed it yet, walks a few buckets
    further back."""
    if slug_override:
        cid, _ = gamma_condition_id(slug_override)
        return slug_override, cid
    start = current_bucket_start()
    slug = None
    for b in range(back, back + 4):
        slug = slug_for_start(start - 300 * b)
        cid, _ = gamma_condition_id(slug)
        if cid:
            return slug, cid
    return slug, None


def window_label(slug):
    """Human-readable window from a slug's unix start (UTC + ET if available)."""
    try:
        ts = int(slug.rsplit("-", 1)[-1])
    except ValueError:
        return slug
    u0 = datetime.fromtimestamp(ts, timezone.utc)
    u1 = datetime.fromtimestamp(ts + 300, timezone.utc)
    label = f"{u0:%H:%M}-{u1:%H:%M} UTC"
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        e0 = datetime.fromtimestamp(ts, et)
        e1 = datetime.fromtimestamp(ts + 300, et)
        label += f"  ({e0:%-I:%M}-{e1:%-I:%M %p} ET)"
    except Exception:
        pass
    return label


# --------------------------------------------------------------------------- #
# Cash-flow signs + measured fees
# --------------------------------------------------------------------------- #
def signed_cash(item):
    t = item.get("type")
    usd = float(item.get("usdcSize") or 0)
    if t == "TRADE":
        return -usd if item.get("side") == "BUY" else +usd
    if t in ("REDEEM", "REWARD", "MERGE"):
        return +usd
    if t == "SPLIT":
        return -usd
    return None


def fee_paid(item):
    if item.get("type") != "TRADE":
        return 0.0
    notional = float(item.get("size") or 0) * float(item.get("price") or 0)
    return abs(float(item.get("usdcSize") or 0) - notional)


def market_trade_share(
    trades,
    *,
    target_slug: str | None = None,
    target_condition_id: str | None = None,
) -> float:
    if not trades:
        return 0.0
    matched = 0
    for trade in trades:
        if target_condition_id and trade.get("conditionId") == target_condition_id:
            matched += 1
            continue
        if target_slug and trade.get("market_slug") == target_slug:
            matched += 1
    return matched / len(trades) * 100


# --------------------------------------------------------------------------- #
# Analysis -> metrics dict (no printing)
# --------------------------------------------------------------------------- #
def compute_metrics(activity, positions, truncated=False):
    trades = [a for a in activity if a.get("type") == "TRADE"]
    ts = [a["timestamp"] for a in activity if a.get("timestamp")]

    by_type_cash, by_type_n = defaultdict(float), defaultdict(int)
    net_cash = 0.0
    for a in activity:
        by_type_n[a.get("type", "?")] += 1
        c = signed_cash(a)
        if c is not None:
            by_type_cash[a.get("type", "?")] += c
            net_cash += c

    volume = sum(float(a.get("usdcSize") or 0) for a in trades)
    fees = sum(fee_paid(a) for a in trades)
    rewards = by_type_cash.get("REWARD", 0.0)
    gross_before_fees = net_cash + fees

    # per-market grouping: cash P&L + net shares held per outcome
    mkts = defaultdict(lambda: {"cash": 0.0, "net": defaultdict(float)})
    for a in activity:
        key = a.get("conditionId") or a.get("slug") or a.get("title") or "?"
        m = mkts[key]
        c = signed_cash(a)
        if c is not None:
            m["cash"] += c
        oc = a.get("outcome", "?")
        sz = float(a.get("size") or 0)
        if a.get("type") == "TRADE":
            m["net"][oc] += sz if a.get("side") == "BUY" else -sz
        elif a.get("type") in ("REDEEM", "MERGE"):
            m["net"][oc] -= sz

    def hedge_score(net):
        vals = sorted((v for v in net.values() if v > 0.5), reverse=True)
        if len(vals) < 2:
            return 0.0
        top2 = vals[0] + vals[1]
        return 1 - abs(vals[0] - vals[1]) / top2 if top2 else 0.0

    resolved = [m for m in mkts.values() if all(abs(v) < 1 for v in m["net"].values())]
    open_mkts = [m for m in mkts.values() if any(abs(v) >= 1 for v in m["net"].values())]
    wins = sum(1 for m in resolved if m["cash"] > 0.005)
    losses = sum(1 for m in resolved if m["cash"] < -0.005)

    tw = sum((sum(abs(v) for v in m["net"].values()) or 1) for m in mkts.values())
    hedge_avg = sum(hedge_score(m["net"]) * (sum(abs(v) for v in m["net"].values()) or 1)
                    for m in mkts.values()) / (tw or 1)

    open_value = sum(float(p.get("currentValue") or 0) for p in positions)
    pm_realized = sum(float(p.get("realizedPnl") or 0) for p in positions)
    pm_unrealized = sum(float(p.get("cashPnl") or 0) for p in positions)
    total_real = net_cash + (open_value if positions else 0)

    return dict(
        n_items=len(activity), n_trades=len(trades),
        t0=datetime.fromtimestamp(min(ts), timezone.utc) if ts else None,
        t1=datetime.fromtimestamp(max(ts), timezone.utc) if ts else None,
        span_h=max(((max(ts) - min(ts)) / 3600) if ts else 0, 1e-9),
        n_markets=len(mkts), n_resolved=len(resolved), n_open=len(open_mkts),
        by_type_cash=dict(by_type_cash), by_type_n=dict(by_type_n),
        net_cash=net_cash, volume=volume, fees=fees,
        gross_before_fees=gross_before_fees, rewards=rewards,
        hedge_avg=hedge_avg, wins=wins, losses=losses,
        open_value=open_value, pm_realized=pm_realized, pm_unrealized=pm_unrealized,
        has_positions=bool(positions), total_real=total_real, truncated=truncated,
        activity=activity,
    )


def classify(m):
    """(is_good, label, reason). Strict bar: a GOOD wallet is provably
    profitable AFTER fees, actually takes a side, and the profit is realized."""
    fee_eaten = m["gross_before_fees"] > 0 and m["net_cash"] < 0
    hedged = m["hedge_avg"] >= HEDGE_MIRAGE
    if m["net_cash"] > 0 and not hedged and not fee_eaten:
        return True, "GOOD", "net positive after fees, directional, realized"
    if hedged:
        return False, "BAD", "hedged both sides (volume/airdrop farm shape)"
    if fee_eaten:
        return False, "BAD", "edge eaten by fees -> net loser"
    if m["net_cash"] <= 0:
        return False, "BAD", "net negative/flat after fees"
    return False, "BAD", "inconclusive"


# --------------------------------------------------------------------------- #
# Reporting (single-wallet verbose)
# --------------------------------------------------------------------------- #
def print_report(m, wallet, *, target_slug=None, target_condition_id=None):
    if m["n_items"] == 0:
        print(WARN(f"{wallet}: no activity found."))
        return
    print(f"\n{HEAD('='*64)}")
    print(HEAD(f"WALLET  {wallet}"))
    print(HEAD('='*64))
    print(f"activity items : {m['n_items']}  ({m['n_trades']} trades)")
    if m["t0"]:
        print(f"time span      : {m['t0']:%Y-%m-%d %H:%M} -> {m['t1']:%Y-%m-%d %H:%M} UTC  ({m['span_h']:.1f}h)")
    print(f"markets touched: {m['n_markets']}  (resolved: {m['n_resolved']}, open: {m['n_open']})")
    if m["truncated"]:
        print(WARN("  NOTE: history capped at ~3000 recent items -> RECENT-WINDOW, not lifetime."))

    print(f"\n{HEAD('-- CASH LEDGER (what actually moved) --')}")
    for t, c in sorted(m["by_type_cash"].items(), key=lambda x: -abs(x[1])):
        print(f"  {t:10} {m['by_type_n'][t]:>5} items   {sgn(c, '{:>+12,.2f}')} USDC")
    print(f"  {BOLD('NET'.ljust(10))} {'':>5}         {sgn(m['net_cash'], '{:>+12,.2f}')} USDC   "
          f"{DIM('<- realized cash profit/loss')}")

    print(f"\n{HEAD('-- TRADING ECONOMICS --')}")
    pct = m["fees"] / m["volume"] * 100 if m["volume"] else 0
    market_trade_pct = market_trade_share(
        m["activity"], target_slug=target_slug, target_condition_id=target_condition_id
    ) if "activity" in m else 0.0
    pace = DIM("(${:,.0f}/day pace)".format(m["volume"] / m["span_h"] * 24))
    fees_str = WARN("${:>11,.2f}".format(m["fees"]))
    pct_str = WARN("({:.2f}% of volume)".format(pct))
    print(f"  volume traded        :  ${m['volume']:>11,.2f}   {pace}")
    print(f"  fees/slippage paid   :  {fees_str}   {pct_str}")
    if target_slug or target_condition_id:
        print(f"  target-market share  :  {market_trade_pct:>6.2f}%   {DIM('(trades in the scanned BTC 5m market)')}")
    print(f"  edge BEFORE fees     : {sgn(m['gross_before_fees'], '${:>+11,.2f}')}")
    print(f"  edge AFTER fees      : {sgn(m['net_cash'], '${:>+11,.2f}')}   {DIM('<- the number that matters')}")
    if m["rewards"]:
        print(f"  of which is REWARDS  : {sgn(m['rewards'], '${:>+11,.2f}')}   {DIM('(farming, not trading)')}")
        print(f"  trading-only P&L     : {sgn(m['net_cash'] - m['rewards'], '${:>+11,.2f}')}")

    print(f"\n{HEAD('-- DIRECTION vs HEDGE --')}")
    print(f"  hedge score          :  {hedgecol(m['hedge_avg'])}   {DIM('(0 = picks a side | 1 = hedged = mirage)')}")
    if m["n_resolved"]:
        tot = m["wins"] + m["losses"]
        wr = m["wins"] / tot * 100 if tot else 0
        print(f"  resolved markets     :  {m['wins']} up, {m['losses']} down   (win rate {(GOOD if wr>=50 else BAD)(f'{wr:.0f}%')})")

    if m["n_open"] and m["has_positions"]:
        print(f"\n{HEAD('-- OPEN / UNREALIZED --')}")
        print(f"  open position value  :  ${m['open_value']:,.2f}")
        print(f"  Polymarket reports   :  realized {sgn(m['pm_realized'])} | unrealized {sgn(m['pm_unrealized'])}")

    is_good, label, reason = classify(m)
    verdict = GOOD("Good for the trader") if is_good else BAD("Bad")
    vol_str = DIM("${:,.0f}".format(m["volume"]))
    print(f"\n  {BOLD('VERDICT:')} {verdict}   {DIM('('+reason+')')}")
    print(f"  {BOLD('Bottom line:')} realized {sgn(m['net_cash'])} after fees on {vol_str} volume.\n")


# --------------------------------------------------------------------------- #
# Seen-wallet files
# --------------------------------------------------------------------------- #
def load_seen(path):
    seen = set()
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#"):
                seen.add(line.split()[0].lower())
    return seen


def append_seen(path, wallet, note):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a") as f:
        if new:
            f.write(
                f"# wallet  label  net  hedge  volume  market_trade_pct  trade_density  reason  scanned_at(UTC)\n"
            )
        f.write(f"{wallet}  {note}\n")


# --------------------------------------------------------------------------- #
# Scan orchestrator
# --------------------------------------------------------------------------- #
def _utcnow():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def scan_market(slug, cid, limit, verbose, pause=0.4):
    """Classify the holders of one already-resolved market. Returns #new done."""
    print(HEAD(f"\n[{_utcnow()}] Market: {slug}"))
    print(f"  window   : {window_label(slug)}")
    print(f"  condition: {cid}")

    try:
        positions = fetch_market_positions(cid, limit=500)
    except requests.RequestException as e:
        print(BAD(f"  Failed to fetch market positions: {e}"))
        return 0
    if not positions:
        print(WARN("  No positions returned for this market."))
        return 0

    processed = load_seen(GOOD_FILE) | load_seen(BAD_FILE)
    # unique wallets, biggest position first
    order, seen_local = [], set()
    for p in positions:
        w = (p.get("proxyWallet") or "").lower()
        if not w or w in seen_local:
            continue
        seen_local.add(w)
        order.append((w, p))

    print(f"  holders  : {len(order)} unique  ({DIM(str(len(processed)) + ' already on file')})\n")

    done = 0
    for w, p in order:
        if limit and done >= limit:
            print(DIM(f"  (reached --limit {limit} new wallets for this window)"))
            break
        if w in processed:
            continue  # silently skip already-classified wallets
        try:
            acts, trunc = fetch_all_activity(w)
            pos = fetch_positions(w)
            m = compute_metrics(acts, pos, trunc)
            m["activity"] = acts
        except requests.RequestException as e:
            print(WARN(f"error {w}: {e} (skipped)"))
            continue

        is_good, label, reason = classify(m)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        density = m["n_trades"] / m["span_h"] * 24 if m["span_h"] else 0.0
        market_trade_pct = market_trade_share(acts, target_slug=slug, target_condition_id=cid)
        note = (f"{label}  net={m['net_cash']:+.2f}  hedge={m['hedge_avg']:.2f}  "
                f"vol={m['volume']:.0f}  market_trade_pct={market_trade_pct:.2f}  "
                f"trade_density={density:.2f}  "
                f"\"{reason}\"  {stamp}")
        append_seen(GOOD_FILE if is_good else BAD_FILE, w, note)
        processed.add(w)
        done += 1

        tag = GOOD("Good for the trader") if is_good else BAD("Bad")
        size = float(p.get("size") or 0)
        print(f"{w}  size={size:>8,.0f}  net={sgn(m['net_cash'])}  hedge={hedgecol(m['hedge_avg'])}  "
              f"-> {tag}  {DIM('(' + reason + ')')}")
        if verbose:
            print_report(m, w, target_slug=slug, target_condition_id=cid)
        time.sleep(pause)

    print(DIM(f"  window done: {done} new wallet(s) classified."))
    return done


def run_scan(back, limit, verbose, slug_override):
    """One-shot scan of a single market (just-closed by default)."""
    slug, cid = resolve_target(back, slug_override)
    if not cid:
        print(BAD(f"\nCould not resolve a conditionId for {slug} (market not indexed yet?)."))
        print(DIM("Try --back 2, or pass --slug explicitly.\n"))
        return
    scan_market(slug, cid, limit, verbose)
    print(f"\n{HEAD('done')}.  Files: {GOOD_FILE}, {BAD_FILE}\n")


def seconds_to_next_window(buffer=10):
    """Seconds until just after the next 5-min boundary (so the market that
    closes on that boundary is settled/indexed before we scan it)."""
    now = time.time()
    nxt = (int(now) // 300) * 300 + 300 + buffer
    return max(1.0, nxt - now)


def run_forever(limit, verbose, buffer=10):
    """Loop indefinitely. Every cycle re-infers the just-closed market from the
    CURRENT time (so slug + positions reset on every 5-min rollover) and scans
    it once. Sleeps until just past the next boundary between scans."""
    print(HEAD("Watching BTC Up/Down 5m — forever. Ctrl-C to stop."))
    last_slug = None
    try:
        while True:
            slug, cid = resolve_target(back=1)          # <-- recomputed each cycle
            if cid and slug != last_slug:
                scan_market(slug, cid, limit, verbose)  # <-- positions re-fetched
                last_slug = slug
            elif not cid:
                print(WARN(f"[{_utcnow()}] couldn't resolve {slug} yet; retrying next cycle"))
            s = seconds_to_next_window(buffer)
            print(DIM(f"[{_utcnow()}] sleeping {s:.0f}s until next 5-min window…"))
            time.sleep(s)
    except KeyboardInterrupt:
        print("\nstopped.")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Judge Polymarket BTC-5m wallets.")
    ap.add_argument("--wallet", help="analyze a single wallet (verbose) instead of scanning")
    ap.add_argument("--slug", help="scan this exact market slug instead of inferring from time")
    ap.add_argument("--back", type=int, default=1,
                    help="how many 5-min windows back to scan (1 = just-closed, default)")
    ap.add_argument("--limit", type=int, default=25,
                    help="max NEW wallets to classify per window (0 = no cap, default 25)")
    ap.add_argument("--loop", action="store_true",
                    help="run forever: re-infer & scan the just-closed market every 5-min window")
    ap.add_argument("--buffer", type=int, default=10,
                    help="seconds to wait past each boundary before scanning (default 10)")
    ap.add_argument("--verbose", action="store_true",
                    help="print the full report for each wallet during a scan")
    args = ap.parse_args()

    if args.wallet:
        acts, trunc = fetch_all_activity(args.wallet)
        pos = fetch_positions(args.wallet)
        print_report(compute_metrics(acts, pos, trunc), args.wallet)
    elif args.loop:
        run_forever(args.limit, args.verbose, args.buffer)
    else:
        run_scan(args.back, args.limit, args.verbose, args.slug)
