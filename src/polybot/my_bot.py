"""CLI entrypoint for the dynamic wallet-filtered example bot."""

import json
import os
from polybot.examples.example_dynamic_random_hold_wallet_filter_copy import create_btc_version
from polybot.examples.example_fixed_dollar_wallet_copy import FixedDollarWalletCopyBot
from polybot.examples.example_btc_five_minute_momentum import create as create_btc_momentum_version
# from polybot.examples.example_dynamic_random_hold import ExampleDynamicRandomHoldBot


def create(_config):
    return create_btc_momentum_version()
    raw_wallets = os.getenv("WALLETS")
    wallets = json.loads(raw_wallets)
    print(len(wallets))
    return create_btc_version(wallets)
