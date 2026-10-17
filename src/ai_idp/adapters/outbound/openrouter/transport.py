from __future__ import annotations

import json

import httpx

from ai_idp.application.services.request_budget import active_request_budget
from ai_idp.domain.errors import ModelInputLimitExceededError


class LimitedTransport(httpx.AsyncBaseTransport):
    """Apply the shared limiter to every HTTP attempt, including SDK retries."""

    def __init__(self, limiter, max_input_bytes: int = 20 * 1024 * 1024) -> None:
        self._limiter = limiter
        self._transport = httpx.AsyncHTTPTransport(retries=0)
        self.reported_cost = 0.0
        self.cost_known = False
        self.requests = 0
        self._max_input_bytes = max_input_bytes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if len(request.content) > self._max_input_bytes:
            raise ModelInputLimitExceededError(
                "Provider request exceeds the configured byte limit."
            )
        model_id = json.loads(request.content).get("model", "unknown")
        async with self._limiter.request(model_id):
            budget = active_request_budget.get()
            if budget:
                budget.reserve()
            self.requests += 1
            response = await self._transport.handle_async_request(request)
            # Do not release capacity before the provider finishes returning its payload.
            await response.aread()
            try:
                usage = response.json().get("usage", {})
                cost = usage.get("cost")
                if isinstance(cost, (int, float)) and cost >= 0:
                    self.reported_cost += cost
                    self.cost_known = True
                    if budget:
                        budget.report_cost(cost)
            except (ValueError, AttributeError, TypeError):
                pass
            return response

    async def aclose(self) -> None:
        await self._transport.aclose()
