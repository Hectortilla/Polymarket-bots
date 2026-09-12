"""Registry of executable example graphs."""

from .entry_exit import entry_exit_example
from .multiple_conditions import multiple_conditions_example
from .random import random_example

GRAPH_EXAMPLES = (entry_exit_example(), multiple_conditions_example(), random_example())
