"""Bounded, explicitly keyed signal consumption for one bot run."""

from dataclasses import dataclass, field

from api.catalog.graphs.numbers import whole_number
from api.catalog.graphs.reasons import GraphReason
from api.catalog.graphs.values import GraphOperation, GraphPort
from api.catalog.node_based.evaluator.values import RuntimeValue

MAX_STATE_KEYS_PER_NODE = 10_000
EVENT_CONTROL_OPERATIONS = frozenset(
    (GraphOperation.COOLDOWN, GraphOperation.ONCE, GraphOperation.DEDUPLICATE)
)


@dataclass(slots=True)
class EventControlState:
    claims: dict[str, dict[str, int | None]] = field(default_factory=dict)

    def evaluate(
        self,
        node_id: str,
        operation: GraphOperation,
        inputs: dict[str, RuntimeValue],
        now_ms: int,
    ) -> RuntimeValue:
        reset = inputs.get(GraphPort.RESET, RuntimeValue(False))
        reset_requested = (
            operation is GraphOperation.ONCE and reset.value is True and reset.available
        )
        enabled = inputs[GraphPort.ENABLED]
        if not reset_requested:
            if not enabled.available:
                return enabled
            if enabled.value is not True:
                return RuntimeValue(False, reason=GraphReason.DISABLED)
        key_value = inputs[GraphPort.KEY]
        if not key_value.available:
            return key_value
        key = key_value.value
        if not isinstance(key, str) or not key.strip():
            return RuntimeValue.invalid(GraphReason.INVALID_KEY)
        duration_ms = 0
        if operation is GraphOperation.COOLDOWN:
            duration_value = inputs[GraphPort.DURATION_MS]
            if not duration_value.available:
                return duration_value
            try:
                duration_ms = whole_number(duration_value.value, "Cooldown duration")
            except ValueError as error:
                return RuntimeValue.invalid(
                    GraphReason.WHOLE_NUMBER_REQUIRED,
                    input_handle_id=GraphPort.DURATION_MS,
                    message=str(error),
                )
        if (
            operation is GraphOperation.ONCE
            and GraphPort.RESET in inputs
            and not reset.available
        ):
            return reset
        claims = self.claims.setdefault(node_id, {})
        if reset_requested:
            claims.pop(key, None)
            return RuntimeValue(False, reason=GraphReason.RESET)
        if operation is GraphOperation.COOLDOWN:
            for expired in tuple(
                key for key, expiry in claims.items() if expiry <= now_ms
            ):
                del claims[expired]
        if key in claims:
            reason = (
                GraphReason.COOLDOWN_ACTIVE
                if operation is GraphOperation.COOLDOWN
                else GraphReason.ALREADY_CONSUMED
            )
            return RuntimeValue(False, reason=reason)
        if len(claims) >= MAX_STATE_KEYS_PER_NODE:
            return RuntimeValue.skipped(GraphReason.STATE_CAPACITY)
        claims[key] = (
            now_ms + duration_ms if operation is GraphOperation.COOLDOWN else None
        )
        return RuntimeValue(True)
