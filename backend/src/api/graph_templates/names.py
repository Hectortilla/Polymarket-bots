"""Dependency-light graph-template naming contract."""

from typing import Annotated

from pydantic import StringConstraints


GRAPH_TEMPLATE_NAME_MAX_LENGTH = 200

type GraphTemplateName = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=GRAPH_TEMPLATE_NAME_MAX_LENGTH,
    ),
]
