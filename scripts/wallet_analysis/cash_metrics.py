"""Cash-flow and fee calculations for wallet activity."""

from polybot.framework.events import Side
from scripts.wallet_payload_contracts import (
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    ActivityRow,
    ActivityType,
)


def signed_cash(activity_row: ActivityRow) -> float | None:
    activity_type = ActivityType(activity_row[ACTIVITY_TYPE_FIELD])
    usdc_size = activity_row[ACTIVITY_USDC_SIZE_FIELD]
    if activity_type is ActivityType.TRADE:
        return (
            -usdc_size
            if Side(activity_row[ACTIVITY_SIDE_FIELD]) is Side.BUY
            else usdc_size
        )
    if activity_type in (ActivityType.REDEEM, ActivityType.REWARD, ActivityType.MERGE):
        return usdc_size
    if activity_type is ActivityType.SPLIT:
        return -usdc_size
    return None


def fee_paid(activity_row: ActivityRow) -> float:
    if ActivityType(activity_row[ACTIVITY_TYPE_FIELD]) is not ActivityType.TRADE:
        return 0.0
    notional = activity_row[ACTIVITY_SIZE_FIELD] * activity_row[ACTIVITY_PRICE_FIELD]
    return abs(activity_row[ACTIVITY_USDC_SIZE_FIELD] - notional)
