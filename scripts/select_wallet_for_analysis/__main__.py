from __future__ import annotations

import curses
import sys

from polymarket.errors import PolymarketError

from scripts.select_wallet_for_analysis.command import print_codex_command
from scripts.select_wallet_for_analysis.export import export_activity
from scripts.select_wallet_for_analysis.picker import pick_row_curses
from scripts.select_wallet_for_analysis.rows import load_good_wallet_rows


def main() -> int:
    try:
        rows = load_good_wallet_rows()
        selected = curses.wrapper(pick_row_curses, rows)
        wallet = str(selected["wallet"])
        data_path = export_activity(wallet)
    except (FileNotFoundError, ValueError, PolymarketError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 1
    print_codex_command(data_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
