"""Recorder dependency provenance stored with archive sessions and features."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


RECORDER_DISTRIBUTION = "polymarket-polybot"
SDK_DISTRIBUTION = "polymarket-client"


def distribution_version(distribution: str) -> str:
    """Return installed distribution provenance without making archives brittle."""

    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"
