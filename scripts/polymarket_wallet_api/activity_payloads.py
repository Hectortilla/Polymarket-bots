"""Official-client activity models normalized into wallet payload fields."""

from datetime import datetime

from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TITLE_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
    SDK_ACTIVITY_TYPE_ATTRIBUTE,
    SDK_AMOUNT_ATTRIBUTE,
    SDK_CONDITION_ID_ATTRIBUTE,
    SDK_OUTCOME_ATTRIBUTE,
    SDK_PRICE_ATTRIBUTE,
    SDK_SHARES_ATTRIBUTE,
    SDK_SIDE_ATTRIBUTE,
    SDK_SLUG_ATTRIBUTE,
    SDK_TIMESTAMP_ATTRIBUTE,
    SDK_TITLE_ATTRIBUTE,
    SDK_TOKEN_ID_ATTRIBUTE,
    SDK_TRANSACTION_HASH_ATTRIBUTE,
    SDK_WALLET_ATTRIBUTE,
)


def activity_payload(model: object) -> dict[str, object]:
    timestamp = getattr(model, SDK_TIMESTAMP_ATTRIBUTE, None)
    if isinstance(timestamp, datetime):
        timestamp = timestamp.timestamp()
    return {
        PROXY_WALLET_FIELD: str(getattr(model, SDK_WALLET_ATTRIBUTE, "") or ""),
        ACTIVITY_TIMESTAMP_FIELD: timestamp,
        CONDITION_ID_FIELD: str(
            getattr(model, SDK_CONDITION_ID_ATTRIBUTE, "") or ""
        ),
        ACTIVITY_TYPE_FIELD: str(getattr(model, SDK_ACTIVITY_TYPE_ATTRIBUTE, "")),
        ACTIVITY_SIZE_FIELD: getattr(model, SDK_SHARES_ATTRIBUTE, None),
        ACTIVITY_USDC_SIZE_FIELD: getattr(model, SDK_AMOUNT_ATTRIBUTE, None),
        ACTIVITY_TRANSACTION_HASH_FIELD: str(
            getattr(model, SDK_TRANSACTION_HASH_ATTRIBUTE, "") or ""
        ),
        ACTIVITY_PRICE_FIELD: getattr(model, SDK_PRICE_ATTRIBUTE, None),
        ACTIVITY_TOKEN_ID_FIELD: str(
            getattr(model, SDK_TOKEN_ID_ATTRIBUTE, "") or ""
        ),
        ACTIVITY_SIDE_FIELD: str(getattr(model, SDK_SIDE_ATTRIBUTE, "")),
        ACTIVITY_TITLE_FIELD: getattr(model, SDK_TITLE_ATTRIBUTE, None),
        ACTIVITY_SLUG_FIELD: getattr(model, SDK_SLUG_ATTRIBUTE, None),
        ACTIVITY_OUTCOME_FIELD: getattr(model, SDK_OUTCOME_ATTRIBUTE, None),
    }
