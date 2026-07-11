import os

from examples.example_price_watcher import ExamplePriceWatcher


def create(config):
    return ExamplePriceWatcher(os.environ["BOT_YES_TOKEN_ID"])