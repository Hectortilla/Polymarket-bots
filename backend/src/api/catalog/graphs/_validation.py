"""Shared graph-contract validation primitives."""


def ensure_unique_values(values: tuple[str, ...], value_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{value_name} values must be unique")


def ensure_unique_graph_trigger_hooks(hook_names: tuple[str, ...]) -> None:
    ensure_unique_values(hook_names, "graph trigger hook")
