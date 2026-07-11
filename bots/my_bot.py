import os

from examples.example_rebound import ExampleReboundBot


def create(config):
    return ExampleReboundBot(
        os.environ.get("BOT_OUTCOME_LABEL", "Yes"),
        market_slug=os.environ.get("BOT_MARKET_SLUG"),
    )
