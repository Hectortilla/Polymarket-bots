"""Runner-owned persistent state paths and naming contracts."""

from pathlib import Path
from hashlib import sha256

BOT_STATE_DIR = Path(".bot-state")
STATE_KEY_DIGEST_LENGTH = 16
SOURCE_ID_STORE_SUFFIX = ".source-ids"
FOLLOWED_WALLET_STORE_SUFFIX = ".followed-wallets.json"
RESOLUTION_LEDGER_SUFFIX = ".resolutions.json"


def state_key(bot_name: str) -> str:
    return sha256(bot_name.encode("utf-8")).hexdigest()[:STATE_KEY_DIGEST_LENGTH]


def state_path(bot_name: str, suffix: str) -> Path:
    return BOT_STATE_DIR / f"{state_key(bot_name)}{suffix}"
