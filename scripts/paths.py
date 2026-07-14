"""Shared filesystem locations for the wallet-analysis scripts."""

from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"
GOOD_FILE = RESULTS_DIR / "good_wallets.txt"
BAD_FILE = RESULTS_DIR / "bad_wallets.txt"
