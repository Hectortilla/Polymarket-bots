"""The complete maintenance vocabulary, parsed once at the CLI boundary."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from api.operations.schema import OperatorAction


class ReadCommand(StrEnum):
    STATUS = "status"
    LIST_RUNS = "list-runs"
    INSPECT_RUN = "inspect-run"

    @property
    def requires_target(self) -> bool:
        return self is ReadCommand.INSPECT_RUN


type OperationCommand = ReadCommand | OperatorAction
ALL_OPERATION_COMMANDS = (*ReadCommand, *OperatorAction)


@dataclass(frozen=True, slots=True)
class CommandRequest:
    command: OperationCommand
    target: UUID | None

    def __post_init__(self) -> None:
        if self.command.requires_target != (self.target is not None):
            raise ValueError(
                "this command requires exactly one UUID target"
                if self.command.requires_target
                else "this command takes no target"
            )
