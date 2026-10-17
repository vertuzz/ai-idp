"""Physical attempt limits shared by concurrent steps and their HTTP retries."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from ai_idp.domain.errors import BudgetExhaustedError


@dataclass
class RequestBudget:
    remaining: int
    used: int = 0
    reported_cost: float = 0.0
    parent: RequestBudget | None = None
    cost_limit: float | None = None

    def reserve(self) -> None:
        if self.used >= self.remaining:
            raise BudgetExhaustedError("Job exhausted its physical model-request budget.")
        if self.cost_limit is not None and self.reported_cost >= self.cost_limit:
            raise BudgetExhaustedError("Job exhausted its estimated spend budget.")
        if self.parent is not None:
            self.parent.reserve()
        self.used += 1

    def report_cost(self, cost: float) -> None:
        self.reported_cost += cost
        if self.parent is not None:
            self.parent.report_cost(cost)


active_request_budget: ContextVar[RequestBudget | None] = ContextVar(
    "active_model_request_budget", default=None
)

active_job_request_budget: ContextVar[RequestBudget | None] = ContextVar(
    "active_job_request_budget", default=None
)
