#!/usr/bin/env python3
"""Pick a good wallet interactively, export its activity, and print a Codex command."""

from __future__ import annotations

import curses
import json
import os
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from backend.bots.scripts.short_wallet_files import load_rows
from backend.bots.scripts.wallets_finder import fetch_all_activity

RESULTS_DIR = Path(__file__).resolve().parent / "results"
GOOD_FILE = RESULTS_DIR / "good_wallets.txt"
DATA_FILENAME_TEMPLATE = "data_{wallet_id}.json"
GAMMA = "https://gamma-api.polymarket.com"
GAMMA_MARKETS_PATH = "/markets"
SORT_CHOICES = (
    ("n", "net", "Net"),
    ("h", "hedge", "Hedge"),
    ("m", "market_trade_pct", "Market share"),
    ("d", "trade_density", "Trade density"),
    ("v", "volume", "Volume"),
    ("t", "scanned_at", "Scanned"),
    ("w", "wallet", "Wallet"),
)
CODEX_PROMPT = """You are an expert quantitative blockchain analyst and market microstructure researcher. 

The attached `data_[wallet_id].json` contains a JSON list of recent operations from a highly successful Polymarket wallet. The wallet is suspected to be a bot operating heavily or exclusively in the "Bitcoin Up or Down 5m" binary options markets.

Your core objective is to reverse-engineer this bot's trading strategy by identifying repeatable mathematical regularities, timing mechanics, and risk management rules.

To ensure a highly rigorous analysis, please structure your workflow and final response around the following directives:

### 1. Quantitative Foundation (Data Verification First)
Before formulating high-level strategy theories, perform an initial programmatic pass of the data to establish baseline metrics. Explicitly calculate and state:
- **Win/Loss Ratio & PnL:** Total trades, win rate, total realized profit/loss, and average ROI per trade.
- **Volume & Sizing:** Mean, median, and maximum position size (in USD/USDC). 
- **Market Concentrated:** Confirm what % of trades are actually in the 5m BTC markets vs. other categories.

### 2. Microstructure & Strategy Deep Dive
Analyze the transaction patterns specifically focusing on:
- **Timing Mechanics:** Group execution timestamps relative to the 5-minute candle windows. Does it enter in the first 30 seconds, snipe the final 10 seconds, or build positions linearly? Look for millisecond/second-level regularities.
- **Position Scaling:** Does it employ a martingale/anti-martingale progression, fixed-fractional sizing, or scale into losing positions (averaging down)?
- **Order Type & Execution:** Based on price impact or execution patterns, is it providing liquidity (limit orders) or taking liquidity (market orders)?
- **Hedging & Arbitrage:** Look for concurrent opposite positions or interactions with correlated markets that suggest delta-neutral or cross-market hedging.

### 3. Structural Output Requirements
Please organize your findings into the following clear sections:
- **Executive Summary:** A 3-sentence summary of the core edge this bot exploits.
- **Empirical Findings:** The raw facts, numbers, and undeniable regularities discovered in the JSON. (Cite specific transaction hashes, timestamps, or blocks where applicable).
- **Hypothesis & Strategy Modeling:** Your reverse-engineered theory of the ruleset. If multiple theories fit, rank them by probability and state what missing data would be required to prove the top hypothesis.
- **Vulnerabilities:** Under what specific market conditions (e.g., high volatility, API latency, low liquidity) does this bot's strategy fail or lose money?

### 4. External Context (Optional API Integration)
If you need to cross-reference contract addresses, market IDs, or resolve resolution details to verify whether a position won or lost, you can reference the Polymarket API documentation: https://docs.polymarket.com/api-reference/introduction. Do not guess resolution outcomes; infer them strictly from payout transactions or state them as assumptions.

Maintain absolute analytical rigor: clearly separate established data facts from your strategic inferences."""

_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _w(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def cyan(text: str) -> str:
    return _w("1;36", text)


def green(text: str) -> str:
    return _w("32", text)


def dim(text: str) -> str:
    return _w("90", text)


def shorten_wallet(wallet: str, prefix: int = 6, suffix: int = 4) -> str:
    if len(wallet) <= prefix + suffix + 3:
        return wallet
    return f"{wallet[:prefix]}...{wallet[-suffix:]}"


def load_good_wallet_rows() -> list[dict]:
    if not GOOD_FILE.exists():
        raise FileNotFoundError(f"missing results file: {GOOD_FILE}")
    with GOOD_FILE.open(encoding="utf-8") as fh:
        rows = load_rows(fh)
    rows.sort(key=lambda row: row["net"], reverse=True)
    return rows


def format_row(row: dict, width: int) -> str:
    wallet = shorten_wallet(row["wallet"])
    scanned_at = row["scanned_at"]
    reason = row["reason"]
    line = (
        f"{wallet:<15}  net={row['net']:+,.2f}  hedge={row['hedge']:.2f}  "
        f"vol={row['volume']:,}  market_trade_pct={row['market_trade_pct']:.2f}  "
        f"trade_density={row['trade_density']:.2f}  "
        f"{row['label']:<5}  {reason}  {scanned_at}"
    )
    return line[: max(0, width - 1)]


def sort_rows(rows: list[dict], sort_key: str, reverse: bool = True) -> list[dict]:
    if sort_key == "scanned_at":
        return sorted(rows, key=lambda row: row.get(sort_key, ""), reverse=reverse)
    return sorted(rows, key=lambda row: row.get(sort_key, 0), reverse=reverse)


def sort_label(sort_key: str) -> str:
    for _, key, label in SORT_CHOICES:
        if key == sort_key:
            return label
    return sort_key


def sort_help_text() -> str:
    shortcuts = " / ".join(
        f"{shortcut}={label}"
        for shortcut, _key_name, label in SORT_CHOICES
    )
    return f"Up/Down move | Enter select | {shortcuts} sort | repeat key reverses | q quit"


def pick_row_curses(stdscr, rows: list[dict]) -> dict:
    if not rows:
        raise ValueError(f"no wallets found in {GOOD_FILE}")
    curses.curs_set(0)
    stdscr.keypad(True)

    sort_key = "net"
    reverse = True
    sorted_rows = sort_rows(rows, sort_key, reverse=reverse)
    selected = 0
    top = 0

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        usable_height = max(1, height - 4)
        top = min(top, max(0, len(sorted_rows) - usable_height))
        selected = max(0, min(selected, len(sorted_rows) - 1))
        if selected < top:
            top = selected
        elif selected >= top + usable_height:
            top = selected - usable_height + 1

        stdscr.addstr(
            0,
            0,
            sort_help_text(),
            curses.A_BOLD,
        )
        stdscr.addstr(
            1,
            0,
            f"{len(sorted_rows)} wallets loaded from {GOOD_FILE} | sort={sort_label(sort_key)} {'desc' if reverse else 'asc'}",
            curses.A_DIM,
        )
        stdscr.addstr(2, 0, "")

        for screen_row, idx in enumerate(
            range(top, min(top + usable_height, len(sorted_rows))),
            start=3,
        ):
            row = sorted_rows[idx]
            line = format_row(row, width)
            attr = curses.A_REVERSE if idx == selected else curses.A_NORMAL
            stdscr.addnstr(screen_row, 0, line, max(0, width - 1), attr)

        stdscr.refresh()

        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(sorted_rows) - 1, selected + 1)
        elif key in (curses.KEY_HOME,):
            selected = 0
        elif key in (curses.KEY_END,):
            selected = len(sorted_rows) - 1
        elif key in (10, 13, curses.KEY_ENTER):
            return sorted_rows[selected]
        else:
            for shortcut, key_name, _label in SORT_CHOICES:
                if key == ord(shortcut):
                    if sort_key == key_name:
                        reverse = not reverse
                    else:
                        sort_key = key_name
                        reverse = True
                    sorted_rows = sort_rows(rows, sort_key, reverse=reverse)
                    selected = 0
                    top = 0
                    break
            else:
                if key in (27, ord("q")):
                    raise KeyboardInterrupt
                continue
            continue
        if key in (27, ord("q")):
            raise KeyboardInterrupt


def export_activity(wallet: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    activity, truncated = fetch_all_activity(wallet)
    market_context = _market_context_from_activity(activity)
    enriched_activity = [
        _enrich_activity_row(row, market_context) for row in activity
    ]
    payload = {
        "wallet": wallet,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "truncated": truncated,
        "activity": enriched_activity,
        "market_context": list(market_context.values()),
    }
    out_path = RESULTS_DIR / DATA_FILENAME_TEMPLATE.format(wallet_id=wallet.lower())
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def _market_context_from_activity(activity: list[dict]) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for row in activity:
        condition_id = row.get("conditionId")
        if not isinstance(condition_id, str) or not condition_id:
            continue
        if condition_id in cache:
            continue
        cache[condition_id] = _fetch_market_context(condition_id)
    return cache


def _fetch_market_context(condition_id: str) -> dict:
    try:
        resp = requests.get(
            f"{GAMMA}{GAMMA_MARKETS_PATH}",
            params={"condition_ids": condition_id, "limit": 1},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException:
        return {"condition_id": condition_id}

    market = None
    if isinstance(payload, list):
        market = payload[0] if payload else None
    elif isinstance(payload, dict):
        markets = payload.get("markets")
        if isinstance(markets, list):
            market = markets[0] if markets else None
        else:
            market = payload

    if not isinstance(market, dict):
        return {"condition_id": condition_id}

    context = {
        "condition_id": market.get("conditionId") or condition_id,
        "market_slug": market.get("slug"),
        "market_name": market.get("question") or market.get("title") or market.get("slug"),
        "market_start_timestamp": _timestamp_from_market_value(
            market.get("startDate") or market.get("start_date"),
        ),
        "market_end_timestamp": _timestamp_from_market_value(
            market.get("endDate") or market.get("end_date"),
        ),
        "market_active": market.get("active"),
        "market_closed": market.get("closed"),
        "market_resolved_outcome": market.get("winningOutcome")
        or market.get("winning_outcome")
        or market.get("resolvedOutcome")
        or market.get("resolved_outcome"),
        "market_outcomes": market.get("outcomes"),
        "market_raw": market,
    }
    return {key: value for key, value in context.items() if value is not None}


def _timestamp_from_market_value(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _enrich_activity_row(row: dict, market_context: dict[str, dict]) -> dict:
    enriched = dict(row)
    condition_id = enriched.get("conditionId")
    if isinstance(condition_id, str) and condition_id in market_context:
        context = market_context[condition_id]
        enriched.update(
            {
                key: value
                for key, value in context.items()
                if key != "market_raw"
            },
        )
        enriched["market_context"] = context
    timestamp = enriched.get("timestamp")
    if isinstance(timestamp, int):
        enriched["timestamp_ms"] = timestamp * 1000
    if enriched.get("market_start_timestamp") is not None and isinstance(timestamp, int):
        enriched["market_offset_seconds"] = timestamp - enriched["market_start_timestamp"]
    side = enriched.get("side")
    outcome = enriched.get("outcome")
    if isinstance(side, str):
        enriched["outcome_token_side"] = side.upper()
    elif isinstance(outcome, str):
        enriched["outcome_token_side"] = outcome
    return enriched


def print_codex_command(data_path: Path) -> None:
    prompt = shlex.quote(CODEX_PROMPT)
    wallet_id = data_path.stem.removeprefix("data_")
    wallet_url = f"https://polymarket.com/es/@{wallet_id}"
    response_path = RESULTS_DIR / f"codex_response_{wallet_id}.txt"
    response_md_path = RESULTS_DIR / f"codex_response_{wallet_id}.md"
    print()
    print(cyan("Wallet URL:"))
    print(f"  {green(wallet_url)}")
    print()
    print(cyan("Exported activity file:"))
    print(f"  {green(str(data_path))}")
    print()
    print(cyan("Codex response file:"))
    print(f"  {green(str(response_path))}")
    print(f"  {dim(f'({response_md_path.name} is the markdown alternative)')}")
    print()
    print(cyan("Copy-paste this command:"))
    command = (
        f"codex --dangerously-bypass-approvals-and-sandbox exec -i {shlex.quote(str(data_path))} "
        f"-m gpt-5.5 "
        f"-c model_reasoning_effort=xhigh "
        f"-c model_reasoning_summary='auto' {prompt}"
    )
    print(f"  {dim(command)}")
    print()
    print(cyan("To save and display the response:"))
    tee_command = (
        f"codex --dangerously-bypass-approvals-and-sandbox exec -i {shlex.quote(str(data_path))} "
        f"-m gpt-5.5 "
        f"-c model_reasoning_effort=xhigh "
        f"-c model_reasoning_summary='auto' {prompt} "
        f"| tee {shlex.quote(str(response_path))}"
    )
    print(f"  {dim(tee_command)}")


def main() -> int:
    try:
        rows = load_good_wallet_rows()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        selected_row = curses.wrapper(pick_row_curses, rows)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    wallet = selected_row["wallet"]
    try:
        data_path = export_activity(wallet)
    except requests.RequestException as exc:
        print(f"Failed to fetch activity for {wallet}: {exc}", file=sys.stderr)
        return 1

    print_codex_command(data_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
