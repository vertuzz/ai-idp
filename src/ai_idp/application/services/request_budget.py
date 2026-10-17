"""Per-step request budget shared with HTTP transports, including SDK retries."""

from contextvars import ContextVar
from dataclasses import dataclass

from ai_idp.domain.errors import BudgetExhaustedError


@dataclass
class RequestBudget:
    remaining: int
    used: int = 0
    reported_cost: float = 0.0

    def reserve(self) -> None:
        if self.used >= self.remaining:
            raise BudgetExhaustedError("Job exhausted its physical model-request budget.")
        self.used += 1


active_request_budget: ContextVar[RequestBudget | None] = ContextVar(
    "active_model_request_budget", default=None
)
