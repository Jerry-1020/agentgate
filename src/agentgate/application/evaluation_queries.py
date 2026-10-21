"""Read the current team's evaluation projections without loading reports."""

import logging
from time import monotonic

from agentgate.server.user_context import get_user_info
from agentgate.storage.evaluation_query_models import EvaluationQuery, TaskSummaryQuery
from agentgate.storage.repository import AgentGateRepository

LOGGER = logging.getLogger(__name__)


class EvaluationQueries:
    def __init__(self, repository: AgentGateRepository):
        self.repository = repository

    def overview(self, query: EvaluationQuery):
        info = get_user_info()
        start = monotonic()
        try:
            result = self.repository.get_evaluation_overview_summary(
                query, user_team_id=info.user_team_id if info else ""
            )
        except Exception:
            LOGGER.exception("Evaluation overview summary query failed")
            raise
        LOGGER.debug(
            "Evaluation overview summary loaded: latency_ms=%.1f", (monotonic() - start) * 1000
        )
        return result

    def tasks(self, query: TaskSummaryQuery):
        info = get_user_info()
        start = monotonic()
        try:
            result = self.repository.list_evaluation_task_summaries(
                query, user_team_id=info.user_team_id if info else ""
            )
        except Exception:
            LOGGER.exception("Evaluation task summary query failed")
            raise
        LOGGER.debug(
            "Evaluation task summaries loaded: count=%d latency_ms=%.1f",
            len(result.items),
            (monotonic() - start) * 1000,
        )
        return result
