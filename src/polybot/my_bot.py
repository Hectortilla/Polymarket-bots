import os

from polybot.examples.example_dynamic_random_hold import ExampleDynamicRandomHoldBot


def create(config):
    return ExampleDynamicRandomHoldBot("btc-updown-5m")
