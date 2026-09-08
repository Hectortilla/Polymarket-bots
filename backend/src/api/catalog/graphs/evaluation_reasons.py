"""Reasons exposed by evaluation, including execution and input failures."""

from enum import StrEnum

from polybot.framework.events import FillRejectReason
from polybot.framework.events.book_validation import BookValidationIssue
from polybot.framework.events.wallet_trades import WalletTradeValidationIssue

from api.catalog.graphs.reasons import GraphReason


class GraphActionSkipReason(StrEnum):
    DISABLED = GraphReason.DISABLED.value
    REQUIRED_INPUT_UNAVAILABLE = "required_input_unavailable"
    BOOK_GAP = "book_gap"
    BOOK_STALE = BookValidationIssue.STALE.value
    WALLET_TRADE_INVALID = WalletTradeValidationIssue.INVALID.value
    WALLET_TRADE_FUTURE_DATED = WalletTradeValidationIssue.FUTURE_DATED.value
    WALLET_TRADE_STALE = WalletTradeValidationIssue.STALE.value


type GraphEvaluationReason = (
    GraphReason
    | GraphActionSkipReason
    | BookValidationIssue
    | WalletTradeValidationIssue
    | FillRejectReason
)
