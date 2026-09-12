from __future__ import annotations

from decimal import InvalidOperation
from typing import TYPE_CHECKING

from ..contracts.kinds import PayloadKind
from .parsing import load_json_object
from .primitives import canonical_json
from .registry import decode_payload_data, encode_payload

if TYPE_CHECKING:
    from ..contracts.payloads import RecordedPayload


def payload_json(payload: RecordedPayload) -> str:
    return canonical_json(encode_payload(payload))


def payload_from_json(kind: str | PayloadKind, raw_json: str) -> RecordedPayload:
    try:
        normalized_kind = PayloadKind(kind)
    except (TypeError, ValueError) as error:
        raise ValueError(f"unsupported recording payload kind: {kind!r}") from error
    data = load_json_object(raw_json)
    try:
        return decode_payload_data(normalized_kind, data)
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        if isinstance(error, ValueError) and str(error).startswith("recording payload"):
            raise
        raise ValueError(
            f"recording payload {normalized_kind.value!r} is malformed"
        ) from error
