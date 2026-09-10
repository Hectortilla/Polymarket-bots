"""One age/count window governs both visible history and eventual physical expiry."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select

from api.bots.models import BotRow
from api.limits.policy import PAPER_BETA
from api.runs.models import RunRow
from api.runs.status import TERMINAL_RUN_STATUSES


class HistorySelection:
    def __init__(self, now: datetime) -> None:
        self._cutoff = now - timedelta(days=PAPER_BETA.history_retention_days)

    def retained_run_ids_query(self, owner_user_id: UUID):
        return (
            select(RunRow.id)
            .join(BotRow, BotRow.id == RunRow.bot_id)
            .where(
                BotRow.owner_user_id == owner_user_id,
                RunRow.status.in_(TERMINAL_RUN_STATUSES),
                ~self._expired_by_age_predicate(),
                RunRow.history_expired_at.is_(None),
            )
            .order_by(RunRow.created_at.desc(), RunRow.id.desc())
            .limit(PAPER_BETA.retained_runs)
        )

    def expired_run_ids_query(self):
        ranked_runs_subquery = (
            select(
                RunRow.id,
                func.row_number()
                .over(
                    partition_by=BotRow.owner_user_id,
                    order_by=(RunRow.created_at.desc(), RunRow.id.desc()),
                )
                .label("history_rank"),
            )
            .join(BotRow, BotRow.id == RunRow.bot_id)
            .where(RunRow.status.in_(TERMINAL_RUN_STATUSES))
            .subquery()
        )
        return (
            select(RunRow.id)
            .join(ranked_runs_subquery, ranked_runs_subquery.c.id == RunRow.id)
            .where(
                or_(
                    RunRow.history_expired_at.is_not(None),
                    ranked_runs_subquery.c.history_rank > PAPER_BETA.retained_runs,
                    self._expired_by_age_predicate(),
                )
            )
            .order_by(RunRow.created_at, RunRow.id)
        )

    def _expired_by_age_predicate(self):
        return func.coalesce(RunRow.ended_at, RunRow.created_at) <= self._cutoff
