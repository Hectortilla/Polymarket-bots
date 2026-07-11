from __future__ import annotations

from pathlib import Path

from polybot.framework.wallets import normalize_wallet_address


def load_seen_wallets(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        normalize_wallet_address(line.split()[0])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


def append_wallet_result(path: Path, wallet: str, note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8") as output:
        if is_new:
            output.write(
                "# wallet label net hedge volume market_trade_pct "
                "trade_density reason scanned_at(UTC)\n"
            )
        output.write(f"{wallet}  {note}\n")
