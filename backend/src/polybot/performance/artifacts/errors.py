"""Lifecycle errors raised while writing performance result artifacts."""

from __future__ import annotations


class PerformanceArtifactError(RuntimeError):
    """Base error for result-artifact lifecycle failures."""


class PerformanceOutputExistsError(PerformanceArtifactError):
    """Raised when a result directory already exists."""


class PerformanceArtifactStateError(PerformanceArtifactError):
    """Raised when an artifact operation is invalid for its lifecycle state."""
