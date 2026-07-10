from __future__ import annotations

import shlex
from pathlib import Path

from scripts.wallets_finder import RESULTS_DIR

CODEX_PROMPT = """Analyze the attached Polymarket wallet activity rigorously. Verify quantitative metrics first, then identify timing, sizing, execution, hedging, and risk-management regularities. Separate empirical facts from hypotheses, cite concrete records, rank competing strategy explanations, and state failure conditions and missing data."""


def print_codex_command(data_path: Path) -> None:
    prompt = shlex.quote(CODEX_PROMPT)
    wallet_id = data_path.stem.removeprefix("data_")
    response_path = RESULTS_DIR / f"codex_response_{wallet_id}.txt"
    command = (
        "codex --dangerously-bypass-approvals-and-sandbox exec "
        f"-i {shlex.quote(str(data_path))} -m gpt-5.5 "
        "-c model_reasoning_effort=xhigh "
        f"-c model_reasoning_summary=auto {prompt}"
    )
    print(f"\nWallet URL: https://polymarket.com/es/@{wallet_id}")
    print(f"Exported activity: {data_path}")
    print(f"Response file: {response_path}")
    print(f"\n{command}\n")
