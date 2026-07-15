from polybot.examples.example_fixed_dollar_wallet_copy import FixedDollarWalletCopyBot
# from polybot.examples.example_dynamic_random_hold import ExampleDynamicRandomHoldBot


def create(_config):
    return FixedDollarWalletCopyBot()
    # return ExampleDynamicRandomHoldBot(slug_prefix="btc-updown-5m")
