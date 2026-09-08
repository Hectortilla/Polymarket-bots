"""Read-only framework views backed by the existing paper accounting owner."""

from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.framework.portfolio import PortfolioPosition, PortfolioSnapshot


class PaperPortfolioReader:
    def __init__(self, portfolio: PaperPortfolio) -> None:
        self._portfolio = portfolio

    def snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            self._portfolio.cash_usdc,
            tuple(
                PortfolioPosition(
                    position.token_id, position.size, position.average_entry_price
                )
                for position in self._portfolio.positions.values()
            ),
        )
