"""Serialized deployment inputs rejected at an adapter or persistence boundary."""


class DeploymentInputError(ValueError):
    """Invalid external deployment data, without echoing its raw contents."""
