"""Official-client position models normalized into wallet payload fields."""

from polybot.polymarket.wallet_activity.fields import (
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
    SDK_CONDITION_ID_ATTRIBUTE,
    SDK_SIZE_ATTRIBUTE,
    SDK_WALLET_ATTRIBUTE,
)
from .position_contracts import (
    SDK_CASH_PNL_ATTRIBUTE,
    SDK_CURRENT_VALUE_ATTRIBUTE,
    SDK_REALIZED_PNL_ATTRIBUTE,
)
from scripts.wallet_payload_fields import (
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
    POSITION_SIZE_FIELD,
)


def position_payload(model: object) -> dict[str, object]:
    return {
        PROXY_WALLET_FIELD: str(getattr(model, SDK_WALLET_ATTRIBUTE, "") or ""),
        CONDITION_ID_FIELD: str(
            getattr(model, SDK_CONDITION_ID_ATTRIBUTE, "") or ""
        ),
        POSITION_SIZE_FIELD: getattr(model, SDK_SIZE_ATTRIBUTE, None),
        POSITION_CURRENT_VALUE_FIELD: getattr(model, SDK_CURRENT_VALUE_ATTRIBUTE, None),
        POSITION_REALIZED_PNL_FIELD: getattr(model, SDK_REALIZED_PNL_ATTRIBUTE, None),
        POSITION_CASH_PNL_FIELD: getattr(model, SDK_CASH_PNL_ATTRIBUTE, None),
    }
