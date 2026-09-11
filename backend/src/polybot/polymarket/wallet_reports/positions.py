"""Complete wallet position reads and bounded market-holder reads via the SDK."""

from collections.abc import Callable
from itertools import islice

from polybot.framework.wallets import validate_wallet_address

from polymarket import PolymarketError, PublicClient

from .contracts import PositionRow
from .errors import WalletReadError, WalletReadReason
from .normalization.positions import normalize_position_rows
from .position_contracts import (
    DEFAULT_MARKET_POSITION_LIMIT,
    MARKET_POSITION_SORT_BY,
    MARKET_POSITION_STATUS,
    POSITION_SIZE_THRESHOLD,
)
from .position_payloads import position_payload
from .query_contracts import DESCENDING_SORT, SDK_PAGE_SIZE
from .scope_validation import require_condition_scope, require_wallet_scope


def fetch_positions(
    wallet: str, *, client_factory: Callable[[], PublicClient] = PublicClient
) -> list[PositionRow]:
    wallet = validate_wallet_address(wallet)
    try:
        with client_factory() as client:
            models = list(
                client.list_positions(
                    user=wallet,
                    size_threshold=POSITION_SIZE_THRESHOLD,
                    page_size=SDK_PAGE_SIZE,
                ).iter_items()
            )
        payloads = [position_payload(model) for model in models]
        require_wallet_scope(payloads, wallet)
        return _validated_positions(payloads)
    except PolymarketError as error:
        raise WalletReadError(WalletReadReason.UNAVAILABLE) from error
    except ValueError as error:
        raise WalletReadError(WalletReadReason.INVALID_RESPONSE) from error


def fetch_market_positions(
    condition_id: str,
    limit: int = DEFAULT_MARKET_POSITION_LIMIT,
    *,
    client_factory: Callable[[], PublicClient] = PublicClient,
) -> list[PositionRow]:
    if limit <= 0:
        raise ValueError("market position limit must be positive")
    try:
        with client_factory() as client:
            envelopes = list(
                islice(
                    client.list_market_positions(
                        market=condition_id,
                        status=MARKET_POSITION_STATUS,
                        sort_by=MARKET_POSITION_SORT_BY,
                        sort_direction=DESCENDING_SORT,
                        page_size=min(limit, SDK_PAGE_SIZE),
                    ).iter_items(),
                    limit,
                )
            )
        payloads = []
        for envelope in envelopes:
            positions = getattr(envelope, "positions", None)
            if not isinstance(positions, (list, tuple)):
                raise WalletReadError(WalletReadReason.INVALID_RESPONSE)
            payloads.extend(position_payload(position) for position in positions)
        require_condition_scope(payloads, condition_id)
        return _validated_positions(payloads)
    except PolymarketError as error:
        raise WalletReadError(WalletReadReason.UNAVAILABLE) from error
    except ValueError as error:
        raise WalletReadError(WalletReadReason.INVALID_RESPONSE) from error


def _validated_positions(payloads: list[dict[str, object]]) -> list[PositionRow]:
    rows = normalize_position_rows(payloads)
    if len(rows) != len(payloads):
        raise WalletReadError(WalletReadReason.INVALID_RESPONSE)
    return rows
